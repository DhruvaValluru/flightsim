"""P6, layered wind shear (core/environment/shear.py): the layered
profile interpolates and reports its layer and gradient, the MIL-F-8785C
log law holds its stated range, the NWP fixture is digest-checked and
placed at standard heights, the spec block validates by name, and a real
c172p run trims and flies in the profile's wind with the wind channel
read back exactly.

Every number asserted here was measured in the container on 2026-09-28
(JSBSim 1.2.4 in .venv). What is NOT claimed: any real forecast (the
fixture is a synthetic stand-in and says so), the specification's z0
values beyond memory, the engine side.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from core.environment import shear
from core.environment.base import Position
from core.environment.shear import (
    CARD_KEYS, MILSPEC_MAX_HEIGHT_FT, MILSPEC_MIN_HEIGHT_FT, TELEMETRY_COLUMNS, LayeredWind,
    MilSpecShear, NwpFixture, ShearError, layer_problems, layers_from_levels, load_fixture,
    milspec_problems, standard_height_m,
)
from core.fdm import units as u
from core.nl.compiler import compile_prompt
from core.record_null import run_null_pair
from core.records import read_records
from core.registry import REGISTRY
from core.scenario.blocks import WIND_PROFILE_KINDS, WindProfileSpec
from core.scenario.card import layered_wind_card_block, write_run_card
from core.scenario.runner import run_spec, wind_profile_for
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate, validate_wind_profile

REPO = Path(__file__).resolve().parents[1]
FIXTURE = "synthetic_profile_2026-09-28"
LAYERS = [[0.0, 5.0, 270.0], [1000.0, 15.0, 260.0], [2000.0, 30.0, 250.0]]


def at(altitude_m, agl_m=None, terrain_m=0.0) -> Position:
    return Position(0.0, 0.0, altitude_m, altitude_m - terrain_m if agl_m is None else agl_m,
                    terrain_m)


def spec_for(text="fly the c172p at 1500 m and 100 kt for 3 seconds with 20 kt wind from 270",
             **fields) -> ScenarioSpec:
    spec = compile_prompt(text)
    spec.set("hold_state", False, frm="test")
    # The compiler reads "wind from 270" as direction 0 (not this item's);
    # the direction is stated explicitly so the crab is a real crosswind's.
    spec.set("wind_speed", 20.0, frm="test")
    spec.set("wind_direction", 270.0, frm="test")
    for name, value in fields.items():
        spec.set(f"wind_profile.{name}", value, frm="test")
    return spec


def names(violations):
    return [v.constraint for v in violations]


# -- the layered profile ----------------------------------------------------------------

def test_layered_wind_interpolates_speed_and_direction_and_reports_layer_and_gradient():
    wind = LayeredWind(LAYERS)
    speed, from_deg, layer, dv_dz = wind.profile_at(at(1500.0))
    assert speed == pytest.approx(u.kt_to_mps(22.5)) and from_deg == pytest.approx(255.0)
    assert layer == 1 and dv_dz == pytest.approx(u.kt_to_mps(15.0) / 1000.0)
    speed, from_deg, layer, dv_dz = wind.profile_at(at(500.0))
    assert speed == pytest.approx(u.kt_to_mps(10.0)) and from_deg == pytest.approx(265.0)
    assert layer == 0 and dv_dz == pytest.approx(u.kt_to_mps(10.0) / 1000.0)
    # Held beyond the first and last layer: no extrapolation, zero gradient.
    assert wind.profile_at(at(-10.0)) == (pytest.approx(u.kt_to_mps(5.0)), 270.0, 0, 0.0)
    assert wind.profile_at(at(5000.0)) == (pytest.approx(u.kt_to_mps(30.0)), 250.0, 2, 0.0)
    vector = wind.wind_at(at(1500.0), 0.0)
    assert vector.horizontal_speed == pytest.approx(u.kt_to_mps(22.5))
    assert wind.last["layer_index"] == 1.0 and wind.evaluations == 1


def test_layered_direction_takes_the_shorter_arc_across_north():
    wind = LayeredWind([[0.0, 10.0, 350.0], [100.0, 10.0, 10.0]])
    assert wind.profile_at(at(50.0))[1] == pytest.approx(0.0)
    assert wind.profile_at(at(25.0))[1] == pytest.approx(355.0)


def test_layer_problems_refuse_by_name():
    """wind_profile.layers: fewer than two, a non-triple, a negative
    altitude, a negative speed, a direction beyond 360, and an unsorted
    list -- each named; a good list gives none."""
    assert layer_problems(LAYERS) == []
    assert names(layer_problems([[0.0, 5.0, 270.0]])) == ["wind_profile.layers"]
    assert names(layer_problems("layers")) == ["wind_profile.layers"]
    assert names(layer_problems([[0.0, 5.0], [10.0, 5.0, 1.0]])) == ["wind_profile.layers"]
    assert names(layer_problems([[-1.0, 5.0, 270.0], [10.0, 5.0, 270.0]])) == ["wind_profile.layers"]
    assert names(layer_problems([[0.0, -5.0, 270.0], [10.0, 5.0, 270.0]])) == ["wind_profile.layers"]
    assert names(layer_problems([[0.0, 5.0, 370.0], [10.0, 5.0, 270.0]])) == ["wind_profile.layers"]
    unsorted = layer_problems([[1000.0, 15.0, 260.0], [0.0, 5.0, 270.0]])
    assert names(unsorted) == ["wind_profile.layers"] and "ascending" in unsorted[0].message
    equal = layer_problems([[0.0, 5.0, 270.0], [0.0, 6.0, 270.0]])
    assert names(equal) == ["wind_profile.layers"]
    with pytest.raises(ShearError) as info:
        LayeredWind([[1000.0, 15.0, 260.0], [0.0, 5.0, 270.0]])
    assert info.value.constraint == "wind_profile.layers"
    assert names(layer_problems([[0.0, True, 270.0], [10.0, 5.0, 270.0]])) == ["wind_profile.layers"]


# -- the MIL-F-8785C log law ---------------------------------------------------------------

def test_the_milspec_log_law_matches_the_specification_form_and_its_range():
    """u(h) = W20 ln(h/z0)/ln(20/z0): u(20 ft) = W20; z0 0.15 ft gives
    12.245 kt at 3 ft and 35.991 kt at 1000 ft for W20 20 kt; z0 2.0 ft
    gives 3.52 and 53.98 kt; held below 3 ft and above 1000 ft with the
    held steps counted; du/dh = W20/(h ln(20/z0))."""
    law = MilSpecShear(20.0, 270.0)
    assert law.z0_ft == 0.15
    assert law.speed_kt_at_agl_ft(20.0) == pytest.approx(20.0)
    assert law.speed_kt_at_agl_ft(3.0) == pytest.approx(12.245341225607353)
    assert law.speed_kt_at_agl_ft(1000.0) == pytest.approx(35.99076693427701)
    assert law.speed_kt_at_agl_ft(2000.0) == law.speed_kt_at_agl_ft(1000.0)
    assert law.speed_kt_at_agl_ft(1.0) == law.speed_kt_at_agl_ft(3.0)
    rough = MilSpecShear(20.0, 270.0, roughness_ft=2.0)
    assert rough.speed_kt_at_agl_ft(3.0) == pytest.approx(20.0 * math.log(1.5) / math.log(10.0))
    assert rough.speed_kt_at_agl_ft(1000.0) == pytest.approx(20.0 * math.log(500.0) / math.log(10.0))
    assert law.dv_dz_per_s(100.0) == pytest.approx(
        u.kt_to_mps(20.0) / (u.ft_to_m(100.0) * math.log(20.0 / 0.15)))
    assert law.dv_dz_per_s(1500.0) == 0.0
    speed, from_deg, layer, dv_dz = law.profile_at(at(u.ft_to_m(100.0)))
    assert speed == pytest.approx(u.kt_to_mps(law.speed_kt_at_agl_ft(100.0))) and layer == 1
    law.profile_at(at(u.ft_to_m(1500.0)))
    assert law.held_steps == 1 and law.profile_at(at(u.ft_to_m(1500.0)))[2] == 2
    assert law.profile_at(at(u.ft_to_m(2.0)))[2] == 0 and law.held_steps == 3
    with pytest.raises(ShearError) as info:
        MilSpecShear(20.0, 270.0, roughness_ft=0.3)
    assert info.value.constraint == "wind_profile.kind"


def test_milspec_problems_name_the_validity_range_and_the_two_roughness_values():
    assert milspec_problems(None, 100.0) == []
    assert milspec_problems(2.0, 3.0) == [] and milspec_problems(0.15, 1000.0) == []
    assert names(milspec_problems(None, 2.0)) == ["wind_profile.kind"]
    assert names(milspec_problems(None, 1000.5)) == ["wind_profile.kind"]
    assert names(milspec_problems(0.3, 100.0)) == ["wind_profile.kind"]
    assert names(milspec_problems(0.3, 5000.0)) == ["wind_profile.kind", "wind_profile.kind"]
    assert (MILSPEC_MIN_HEIGHT_FT, MILSPEC_MAX_HEIGHT_FT) == (3.0, 1000.0)


# -- the NWP fixture ----------------------------------------------------------------------

def test_the_committed_fixture_loads_with_its_digest_and_says_it_is_synthetic():
    loaded = load_fixture(FIXTURE)
    assert loaded["sha256"] == hashlib.sha256(
        (REPO / "assets/nwp" / f"{FIXTURE}.json").read_bytes()).hexdigest()
    assert loaded["provenance"]["sha256"] == loaded["sha256"]
    assert loaded["provenance"]["synthetic"] is True
    assert loaded["provenance"]["fetched_at"] is None
    assert loaded["provenance"]["url"].startswith("https://nomads.ncep.noaa.gov/")
    assert len(loaded["levels"]) == 5 and loaded["levels"][0][0] == 1000.0
    for name in (f"{FIXTURE}.json", f"{FIXTURE}.provenance.json", "README.md"):
        assert (REPO / "assets/nwp" / name).read_text(encoding="utf-8").isascii()


def test_the_levels_sit_at_standard_atmosphere_heights_ascending():
    """1000 hPa -> 110.9 m, 925 -> 762.1, 850 -> 1457.7, 700 -> 3013.6,
    500 -> 5579.4 m (JSBSim's own layer inversion, transcribed in P1)."""
    assert standard_height_m(1013.25) == pytest.approx(0.0, abs=0.5)
    assert [round(standard_height_m(p), 1) for p in (1000, 925, 850, 700, 500)] == [
        110.9, 762.1, 1457.7, 3013.6, 5579.4]
    layers = layers_from_levels([[500.0, 18.0, 24.0], [1000.0, 3.0, 4.0]])
    assert layers[0][0] < layers[1][0]                       # sorted by height
    assert layers[0][1] == pytest.approx(u.mps_to_kt(5.0))
    assert layers[0][2] == pytest.approx(math.degrees(math.atan2(-3.0, -4.0)) % 360.0)
    fixture = NwpFixture(FIXTURE)
    assert fixture.kind == "nwp" and len(fixture.layers) == 5
    assert fixture.profile_at(at(1500.0))[2] == 2
    assert fixture.card_block()["kind"] == "nwp" and "sha256" in fixture.card_block()["source"]
    assert "synthetic stand-in" in " ".join(fixture.not_claimed())


def test_a_missing_or_altered_fixture_refuses_by_name(tmp_path):
    with pytest.raises(ShearError) as info:
        load_fixture("no_such_profile")
    assert info.value.constraint == "weather.fixture_missing"
    with pytest.raises(ShearError) as info:
        load_fixture(None)
    assert info.value.constraint == "weather.fixture_missing"
    data = (REPO / "assets/nwp" / f"{FIXTURE}.json").read_text(encoding="utf-8")
    sidecar = (REPO / "assets/nwp" / f"{FIXTURE}.provenance.json").read_text(encoding="utf-8")
    # newline="\n": the digest is over bytes, and a Windows write_text would
    # turn the fixture's LF into CRLF (measured: CI run 36509604836).
    (tmp_path / f"{FIXTURE}.json").write_text(data.replace("3.0", "3.5"), encoding="utf-8", newline="\n")
    (tmp_path / f"{FIXTURE}.provenance.json").write_text(sidecar, encoding="utf-8", newline="\n")
    with pytest.raises(ShearError) as info:
        load_fixture(FIXTURE, tmp_path)
    assert info.value.constraint == "weather.fixture_digest"
    (tmp_path / f"{FIXTURE}.json").write_text(data, encoding="utf-8", newline="\n")
    assert load_fixture(FIXTURE, tmp_path)["levels"][0] == [1000.0, 3.0, 4.0]
    (tmp_path / f"{FIXTURE}.provenance.json").unlink()
    with pytest.raises(ShearError) as info:
        load_fixture(FIXTURE, tmp_path)
    assert info.value.constraint == "weather.fixture_missing"


# -- the spec block and its validation ---------------------------------------------------

def test_the_block_defaults_to_uniform_and_is_absent_canonical():
    spec = compile_prompt("fly the c172p at 1500 m and 100 kt for 3 seconds")
    assert spec.wind_profile.is_default() and "wind_profile" not in spec.to_dict()
    assert WindProfileSpec.FIELD_ORDER == ("kind", "layers", "roughness_ft", "fixture")
    assert WIND_PROFILE_KINDS == ("uniform", "layered", "milspec", "nwp")
    before = spec.digest()
    spec.set("wind_profile.kind", "layered")
    spec.set("wind_profile.layers", LAYERS)
    assert spec.digest() != before
    reread = ScenarioSpec.from_dict(json.loads(json.dumps(spec.to_dict())))
    assert reread.digest() == spec.digest()
    assert list(reread.to_dict()["wind_profile"]) == list(WindProfileSpec.FIELD_ORDER)
    with pytest.raises(ValueError):
        spec.plan("wind_profile.kind", "uniform", frm="planner")   # a stated value never moves


def test_validation_refuses_each_profile_problem_by_name():
    assert names(validate_wind_profile(spec_for())) == []
    assert names(validate_wind_profile(spec_for(kind="spiral"))) == ["wind_profile.kind"]
    assert names(validate_wind_profile(spec_for(kind="layered"))) == ["wind_profile.layers"]
    assert names(validate_wind_profile(spec_for(kind="layered", layers=LAYERS))) == []
    assert names(validate_wind_profile(spec_for(kind="layered", layers=[LAYERS[1], LAYERS[0]]))) == ["wind_profile.layers"]
    assert names(validate_wind_profile(spec_for(kind="layered", layers=[LAYERS[0]]))) == ["wind_profile.layers"]
    assert names(validate_wind_profile(spec_for(kind="layered", layers=[[-5.0, 5.0, 270.0], LAYERS[1]]))) == ["wind_profile.layers"]
    # milspec: the c172p scene at 1500 m is above the law's 1000 ft.
    assert names(validate_wind_profile(spec_for(kind="milspec"))) == ["wind_profile.kind"]
    low = spec_for("fly the c172p at 100 m and 100 kt for 3 seconds with 20 kt wind from 270")
    low.set("wind_profile.kind", "milspec")
    assert names(validate_wind_profile(low)) == []
    low.set("wind_profile.roughness_ft", 0.3)
    assert names(validate_wind_profile(low)) == ["wind_profile.kind"]
    low.set("wind_profile.roughness_ft", 2.0)
    assert names(validate_wind_profile(low)) == []
    # nwp: the fixture must exist and match.
    assert names(validate_wind_profile(spec_for(kind="nwp"))) == ["weather.fixture_missing"]
    assert names(validate_wind_profile(spec_for(kind="nwp", fixture="nope"))) == ["weather.fixture_missing"]
    assert names(validate_wind_profile(spec_for(kind="nwp", fixture=FIXTURE))) == []
    # Another kind's field beside a non-uniform kind: one profile at a time.
    assert names(validate_wind_profile(spec_for(kind="nwp", fixture=FIXTURE, layers=LAYERS))) == ["wind_profile.kind"]
    # Under the uniform kind a companion field is carried, not applied (the
    # null pair of ``kind`` is that spec): no refusal.
    assert names(validate_wind_profile(spec_for(kind="uniform", layers=LAYERS))) == []
    report = validate(spec_for(kind="layered", layers=[LAYERS[1], LAYERS[0]]), check_feasibility=False)
    assert "[wind_profile.layers]" in report.render()


def test_every_wind_profile_field_is_registered_with_recorded_effect_channels():
    fields = {f"wind_profile.{f}" for f in WindProfileSpec.FIELD_ORDER}
    assert fields <= set(REGISTRY.spec_fields())
    assert REGISTRY.get("wind_profile.kind").null_value == "uniform"
    for name in fields:
        assert REGISTRY.get(name).spec_section == "wind_profile"


# -- a real run -----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def layered_run():
    return run_spec(spec_for(kind="layered", layers=LAYERS))


@pytest.fixture(scope="module")
def uniform_run():
    return run_spec(spec_for())


def test_the_layered_run_flies_in_the_layers_wind_and_reads_it_back_exactly(layered_run, uniform_run):
    """At 1500 m the layers give 22.5 kt = 11.575 m/s (the uniform spec
    wind is 20 kt = 10.289 m/s), layer index 1, dV/dz 0.00772 1/s; the
    wind channel reads back with 0.0 error on every step; the aircraft
    crabs against a different wind (measured 9.01 deg at the end)."""
    cols = layered_run.telemetry.columns
    for column in TELEMETRY_COLUMNS:
        assert column in cols and len(cols[column]) == len(layered_run.telemetry)
    assert cols["wind_profile_speed_mps"][1] == pytest.approx(11.575, rel=1e-4)   # one step off 1500 m
    assert cols["wind_layer_index"][1] == 1.0
    assert cols["shear_dv_dz_per_s"][1] == pytest.approx(u.kt_to_mps(15.0) / 1000.0)
    assert uniform_run.telemetry.columns["wind_profile_speed_mps"][1] == pytest.approx(u.kt_to_mps(20.0))
    assert set(uniform_run.telemetry.columns["wind_layer_index"]) == {0.0}
    assert set(uniform_run.telemetry.columns["shear_dv_dz_per_s"]) == {0.0}
    delivery = layered_run.manifest["environment_delivery"]
    assert delivery["wind"]["max_abs_error"] == {p: 0.0 for p in shear.WIND_PROPERTIES}
    assert delivery["wind"]["steps_checked"] == 359 and delivery["wind"]["steps_written"] == 360
    assert delivery["wind_profile"] == {"kind": "layered", "applied": True, "reads": ["layers"],
                                        "unread_stated_fields": [], "note": ""}
    assert layered_run.output_digest != uniform_run.output_digest
    assert abs(cols["crab_deg"][-1]) > abs(uniform_run.telemetry.columns["crab_deg"][-1])
    provenance = [p for p in layered_run.manifest["environment"] if p["name"] == "layered_wind"]
    assert provenance and provenance[0]["carries_base_wind"] is True
    assert not any(p["name"] == "steady_wind" for p in layered_run.manifest["environment"])


def test_the_layered_run_returns_the_kind_and_layers_records(layered_run):
    records = {r["name"]: r for r in read_records(layered_run.manifest["applied_variables"])}
    kind = records["wind_profile.kind"]
    assert kind["value"] == "layered" and kind["source"] == "user" and kind["unit"] == "word"
    assert kind["properties_written"] == list(shear.WIND_PROPERTIES)
    assert [w["property"] for w in kind["jsbsim_writes"]] == list(shear.WIND_PROPERTIES)
    assert kind["readback"]["agrees"] and kind["readback"]["property"] == "atmosphere/wind-north-fps"
    assert kind["readback"]["tolerance"] == 0.0
    assert kind["null_test"]["with"] == pytest.approx(11.575)
    assert kind["null_test"]["without"] == pytest.approx(u.kt_to_mps(20.0))
    assert kind["null_test"]["ok"] and kind["null_test"]["kind"] == "reached"
    assert kind["telemetry_columns"] == list(TELEMETRY_COLUMNS)
    assert kind["model"]["name"].startswith("layered wind")
    assert kind["parameters"]["per_step_readback"]["agrees"] is True
    layers = records["wind_profile.layers"]
    assert layers["value"] == LAYERS and layers["unit"] == "[m, kt, deg]"
    assert "wind_profile.roughness_ft" not in records and "wind_profile.fixture" not in records
    assert json.dumps(layered_run.manifest).isascii()


def test_the_layered_null_pair_measures_the_layers_speed_at_the_altitude():
    """layered vs uniform on the c172p (1500 m, 3 s): wind_profile_speed_mps
    moves 1.2865 m/s (22.5 - 20 kt), dV/dz 0.0077 1/s and the layer index
    1 (reported, no floor), altitude 3.43 m (a crosswind from 270; a
    headwind change measured 15.8 m); verdict reached."""
    pair = run_null_pair(spec_for(kind="layered", layers=LAYERS), "wind_profile.kind")
    assert pair.verdict == "reached" and pair.digests_differ
    effect = pair.to_dict()["effect"]
    assert effect["wind_profile_speed_mps"]["peak_abs"] == pytest.approx(1.2865, abs=1e-3)
    assert effect["wind_profile_speed_mps"]["reached"] is True
    assert effect["shear_dv_dz_per_s"]["peak_abs"] == pytest.approx(0.0077167, abs=1e-5)
    assert effect["wind_layer_index"]["peak_abs"] == 1.0 and effect["wind_layer_index"]["reached"] is None
    assert effect["altitude_m"]["peak_abs"] == pytest.approx(3.43, abs=0.3)
    assert effect["altitude_m"]["reached"] is True


def test_the_layers_and_fixture_pairs_are_refused_by_name_because_their_kind_needs_them():
    """The null of ``layers`` / ``fixture`` is the field unstated, which the
    layered / nwp kind refuses (wind_profile.layers, weather.fixture_missing):
    the variable that moves between profiles is ``kind``, and its pair runs."""
    from core.scenario.validate import ValidationError

    with pytest.raises(ValidationError) as info:
        run_null_pair(spec_for(kind="layered", layers=LAYERS), "wind_profile.layers")
    assert "[wind_profile.layers]" in str(info.value)
    with pytest.raises(ValidationError) as info:
        run_null_pair(spec_for(kind="nwp", fixture=FIXTURE), "wind_profile.fixture")
    assert "[weather.fixture_missing]" in str(info.value)


@pytest.mark.timeout(300)
def test_the_milspec_and_nwp_runs_deliver_their_profiles():
    low = spec_for("fly the c172p at 100 m and 100 kt for 3 seconds with 20 kt wind from 270")
    low.set("wind_profile.kind", "milspec")
    run = run_spec(low)
    cols = run.telemetry.columns
    law = MilSpecShear(20.0, 270.0)
    h_ft = u.m_to_ft(cols["agl_m"][1])
    # The wind is evaluated at the pre-step position and the sample taken
    # after the step: one step's altitude change (1e-5 relative) apart.
    assert cols["wind_profile_speed_mps"][1] == pytest.approx(
        u.kt_to_mps(law.speed_kt_at_agl_ft(h_ft)), rel=1e-4)
    assert cols["shear_dv_dz_per_s"][1] == pytest.approx(law.dv_dz_per_s(h_ft), rel=1e-4)
    assert cols["wind_layer_index"][1] == 1.0
    records = {r["name"]: r for r in read_records(run.manifest["applied_variables"])}
    assert records["wind_profile.kind"]["value"] == "milspec"
    assert records["wind_profile.kind"]["parameters"]["z0_ft"] == 0.15
    assert records["wind_profile.kind"]["null_test"]["ok"]      # u(328 ft) != W20
    nwp = run_spec(spec_for(kind="nwp", fixture=FIXTURE))
    fixture = NwpFixture(FIXTURE)
    assert nwp.telemetry.columns["wind_profile_speed_mps"][1] == pytest.approx(
        fixture.profile_at(at(nwp.telemetry.columns["altitude_m"][1]))[0], rel=1e-4)
    records = {r["name"]: r for r in read_records(nwp.manifest["applied_variables"])}
    assert records["wind_profile.fixture"]["value"] == FIXTURE
    assert records["wind_profile.kind"]["parameters"]["synthetic"] is True
    assert "synthetic stand-in" in " ".join(records["wind_profile.kind"]["not_claimed"])


def test_the_layered_wind_card_block_has_the_fixed_keys_and_rides_on_the_card(tmp_path):
    assert layered_wind_card_block(spec_for()) is None
    block = layered_wind_card_block(spec_for(kind="layered", layers=LAYERS))
    assert tuple(block) == CARD_KEYS == ("kind", "layers", "z0_ft", "source")
    assert block == {"kind": "layered", "layers": LAYERS, "z0_ft": None, "source": "spec"}
    low = spec_for("fly the c172p at 100 m and 100 kt for 3 seconds with 20 kt wind from 270")
    low.set("wind_profile.kind", "milspec")
    milspec = layered_wind_card_block(low)
    assert milspec["z0_ft"] == 0.15 and len(milspec["layers"]) == 9
    assert milspec["layers"][3] == pytest.approx([u.ft_to_m(20.0), 20.0, 270.0])
    nwp = layered_wind_card_block(spec_for(kind="nwp", fixture=FIXTURE))
    assert nwp["kind"] == "nwp" and len(nwp["layers"]) == 5 and "sha256" in nwp["source"]
    path = write_run_card(spec_for(kind="layered", layers=LAYERS), tmp_path / "card.json")
    card = json.loads(path.read_text(encoding="utf-8"))
    assert card["layered_wind"] == block and card["wind_speed_kt"] == 20.0
    assert "gust_table" not in card and path.read_text(encoding="utf-8").isascii()
    plain = json.loads(write_run_card(spec_for(), tmp_path / "plain.json").read_text(encoding="utf-8"))
    assert "layered_wind" not in plain


def test_wind_profile_for_returns_the_provider_the_spec_names():
    assert wind_profile_for(spec_for()) is None
    assert isinstance(wind_profile_for(spec_for(kind="layered", layers=LAYERS)), LayeredWind)
    assert isinstance(wind_profile_for(spec_for(kind="nwp", fixture=FIXTURE)), NwpFixture)
    provider = wind_profile_for(spec_for(kind="layered", layers=LAYERS))
    assert provider.stated["kind"]["value"] == "layered" and provider.stated["fixture"] is None
    assert provider.uniform_speed_mps == pytest.approx(u.kt_to_mps(20.0))
    assert (REPO / "core/environment/shear.py").read_text(encoding="utf-8").isascii()


def test_the_profiles_wind_is_written_before_the_trim_and_the_trim_resets_it():
    """configure_from_spec writes the profile's wind (22.5 kt from 255 deg
    at 1500 m) before the trim in place of the spec's uniform 20 kt.
    Measured on JSBSim 1.2.4: the trim itself resets atmosphere/wind-*-fps
    to 0 (both trim modes; the trimmed throttle is 0.7392 with and without
    a wind), so the trim solves in still air for the uniform and the
    profile kinds alike and the first per-step write restores the wind --
    a stated limitation (docs/JSBSIM_CORRECTIONS.md 18), pinned here so a
    fix is measured, not assumed."""
    from core.scenario.runner import (
        configure_from_spec, environment_for, fdm_at_initial_conditions, trim_wind_fps,
    )

    spec = spec_for(kind="layered", layers=LAYERS)
    stack = environment_for(spec)
    fdm = fdm_at_initial_conditions(spec)
    stack.prepare(fdm)
    north, east = trim_wind_fps(spec, stack, fdm)
    expected = LayeredWind(LAYERS).wind_at(at(1500.0), 0.0)
    assert (u.fps_to_mps(north), u.fps_to_mps(east)) == pytest.approx(
        (expected.north, expected.east), abs=1e-6)
    assert u.fps_to_mps(math.hypot(north, east)) == pytest.approx(u.kt_to_mps(22.5), abs=1e-6)
    plain = spec_for()
    north, east = trim_wind_fps(plain, environment_for(plain), fdm_at_initial_conditions(plain))
    assert u.fps_to_mps(east) == pytest.approx(u.kt_to_mps(20.0), abs=1e-6)
    assert abs(north) < 1e-9
    # The reset, measured: after the trim the property reads ~0 and the
    # trimmed throttle is the still-air one; the first apply restores it.
    fdm = configure_from_spec(spec, stack)
    assert abs(fdm.props.get("atmosphere/wind-east-fps")) < 1e-9
    assert fdm.props.get("fcs/throttle-cmd-norm") == pytest.approx(0.7392, abs=2e-3)
    stack.configure(fdm)
    stack.apply(fdm)
    assert u.fps_to_mps(fdm.props.get("atmosphere/wind-east-fps")) == pytest.approx(expected.east, abs=1e-6)
