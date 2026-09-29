"""Phase 2, package F: the randomisation POLICY (contracts §5).

Every leaf of ``randomization.policy`` is drawn by the one sampler,
seeded per leaf and attempt from (draw index, campaign seed), written
with ``Source.SAMPLED`` and the contract's detail, never re-planned;
every attempt goes through validate(); a refused draw is COUNTED and
re-drawn, an exhausted slot refuses ``randomization.infeasible`` by
name; the Phase 10 leaves keep their streams and outputs. The
realised distribution is a number with a picture.
"""

import json
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

from core.nl.compiler import compile_prompt
from core.scenario.camera import CameraSpec
from core.scenario.fields import PLANNABLE_SOURCES, Quantity, Source
from core.scenario.randomization import (
    HOUR_WINDOWS, MAX_POLICY_ATTEMPTS, MAX_SEED, PLANNABLE, POLICY_CAMERA_LEAVES,
    POLICY_LEAVES, RandomizationError, RandomizationSpec, _draw, card_block,
    policy_stream, realised_distribution, render_look, sample_randomization,
)
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate
from core.scene import weather_visuals as wv

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
PROMPT = "fly at 10000 ft and 280 kt for 60 seconds"

#: The contracts §5.2 policy with the Rockies (no bake) replaced by
#: ranges that have one, so the whole thing can draw.
POLICY = {
    "location": {"choice": ["alps", "yosemite", "great_plains"], "weights": [3, 2, 1]},
    "weather_date": {"uniform_dates": ["2024-01-01", "2024-12-31"]},
    "hour_local": {"uniform": [5.5, 20.0]},
    "sun_elevation_min_deg": 2,
    "visibility_km": {"lognormal": {"median": 25, "sigma": 0.6}, "clip": [1, 80]},
    "cloud_cover": {"beta": [2, 2]},
    "precipitation": {"choice": ["none", "rain", "snow"], "weights": [7, 2, 1],
                      "gated_by": "cloud_cover > 0.6"},
    "wind_speed_kt": {"weibull": {"k": 2.0, "lambda": 12}},
    "turbulence": {"choice": ["none", "light", "moderate", "severe"],
                   "weights": [4, 3, 2, 1]},
    "surface": {"choice": ["grassland", "desert", "forest", "city", "ocean"]},
    "aircraft": {"choice": ["A320", "B747"]},
    "livery": {"choice": ["default"]},
    "traffic_count": {"poisson": 0.7, "max": 2},
    "cameras": {"preset": {"choice": ["chase", "tower", "wingman", "ground"]},
                "focal_length_mm": {"loguniform": [24, 400]},
                "offset_jitter_m": {"normal": {"sigma": 5}}},
}


def _spec(policy=None, prompt=PROMPT, camera=True, seed=11):
    spec = compile_prompt(prompt)
    if camera:
        spec.cameras = [CameraSpec.defaulted(
            camera_id="camera0", preset="chase", aircraft=str(spec.aircraft.value),
            terrain_elevation_m=float(spec.terrain_elevation.value))]
    if policy is not None:
        spec.set("randomization.policy", policy, frm="test policy")
    if seed is not None:
        spec.set("randomization.seed", seed, frm="test")
    return spec


# -- Source.SAMPLED --------------------------------------------------------

def test_sampled_joins_the_enum_between_inferred_and_model_and_is_never_plannable():
    members = list(Source)
    assert members.index(Source.INFERRED) < members.index(Source.SAMPLED) \
        < members.index(Source.MODEL)
    assert Source("sampled") is Source.SAMPLED and str(Source.SAMPLED) == "sampled"
    assert Source.SAMPLED not in PLANNABLE_SOURCES
    assert Source.SAMPLED not in PLANNABLE
    from webapp.runs import PLANNABLE_SOURCES as WEB
    assert "sampled" not in WEB


def test_a_sampled_field_is_never_re_planned_by_any_door():
    """The immutability the contract states: once drawn, a field is as
    fixed as a user's -- block, spec and camera plan() all refuse by
    name, and the Phase 10 sampler skips it."""
    spec = _spec({"visibility_km": {"uniform": [10, 12]},
                  "wind_speed_kt": {"uniform": [5, 6]},
                  "cameras": {"focal_length_mm": {"uniform": [50, 60]}}})
    sample_randomization(spec)
    assert spec.randomization.visibility_km.source is Source.SAMPLED
    with pytest.raises(ValueError, match="never silently moved"):
        spec.randomization.plan("visibility_km", 1.0, frm="planner")
    with pytest.raises(ValueError, match="never silently moved"):
        spec.plan("randomization.fog_density", 0.5, frm="planner")
    with pytest.raises(ValueError, match="never silently moved"):
        spec.plan("wind_speed", 0.0, frm="planner")
    with pytest.raises(ValueError, match="never silently moved"):
        spec.plan("cameras[0].focal_length_mm", 35.0, frm="planner")
    # A second pass leaves every sampled number exactly where it was:
    # the fog stream does not re-draw a fog the policy derived.
    before = spec.to_dict()
    sample_randomization(spec)
    assert spec.to_dict() == before
    assert float(spec.randomization.fog_density.value) == pytest.approx(
        wv.fog_extinction_per_m(float(spec.randomization.visibility_km.value)),
        rel=1e-5)
    assert spec.randomization.fog_density.source is Source.SAMPLED


# -- the block's spec-8 leaves are absent-canonical --------------------------

def test_the_phase10_block_keeps_its_twenty_keys_and_its_draws():
    """No policy: the block serialises exactly as at spec 8 stage 1 (the
    20 FIELD_ORDER keys, none of the policy placeholders) and the
    Phase 10 example draws the same numbers from the same streams."""
    spec = ScenarioSpec.read(EXAMPLES / "randomized.yaml")
    sample_randomization(spec)
    block = spec.to_dict()["randomization"]
    assert set(block) == set(RandomizationSpec.FIELD_ORDER[:20])
    assert not (set(block) & set(RandomizationSpec.POLICY_FIELDS))
    assert spec.randomization.policy_draws.value is None
    reread = ScenarioSpec.from_dict(json.loads(json.dumps(spec.to_dict())))
    assert reread.to_dict() == spec.to_dict()
    assert "look" not in card_block(spec)          # no policy: the Phase 10 card
    assert set(render_look(spec)) > {"sun_elev", "sun_azim", "exposure_bias",
                                     "fog_density"}
    # And the four flag values are the block's own numbers.
    look = render_look(spec)
    assert look["fog_density"] == float(spec.randomization.fog_density.value)


def test_the_phase10_leaves_draw_the_same_numbers_beside_a_policy():
    """A policy that names none of the Phase 10 leaves leaves their
    streams untouched: same seed, same day, hour, fog and jitter as an
    enabled block with no policy."""
    plain = _spec(seed=5)
    plain.set("randomization.enabled", True, frm="test")
    sample_randomization(plain)
    with_policy = _spec({"traffic_count": {"poisson": 0.7, "max": 2}}, seed=5)
    sample_randomization(with_policy)
    for name in ("day_of_year", "hour_utc", "sun_elevation_deg", "fog_density",
                 "exposure_bias", "livery"):
        assert getattr(with_policy.randomization, name).value == \
            getattr(plain.randomization, name).value, name
    assert with_policy.cameras[0].offset_right_m.value == \
        plain.cameras[0].offset_right_m.value
    assert with_policy.randomization.traffic_count.source is Source.SAMPLED
    assert with_policy.randomization.enabled.source is Source.DERIVED


# -- distributions and seeds -------------------------------------------------

@pytest.mark.parametrize("leaf,check", [
    ({"uniform": [3.0, 4.0]}, lambda v: 3.0 <= v <= 4.0),
    ({"loguniform": [1.0, 1000.0]}, lambda v: 1.0 <= v <= 1000.0),
    ({"normal": {"mean": 10.0, "sigma": 0.0001}}, lambda v: abs(v - 10.0) < 0.01),
    ({"lognormal": {"median": 25.0, "sigma": 0.0001}}, lambda v: abs(v - 25.0) < 0.1),
    ({"beta": [2, 2]}, lambda v: 0.0 <= v <= 1.0),
    ({"weibull": {"k": 2.0, "lambda": 12.0}}, lambda v: v >= 0.0),
    ({"poisson": 0.7, "max": 2}, lambda v: v in (0, 1, 2)),
    ({"choice": ["a", "b", "c"], "weights": [1, 0, 1]}, lambda v: v in ("a", "c")),
    ({"choice": ["only"]}, lambda v: v == "only"),
    ({"uniform_dates": ["2024-03-01", "2024-03-03"]},
     lambda v: v in ("2024-03-01", "2024-03-02", "2024-03-03")),
])
def test_every_documented_form_draws_inside_its_support(leaf, check):
    rng = np.random.default_rng(3)
    for _ in range(200):
        assert check(_draw(rng, leaf)), leaf


def test_streams_are_per_leaf_per_attempt_from_draw_index_and_campaign_seed():
    a, seed_a = policy_stream(20260924, 0, 0, "randomization.policy.visibility_km")
    b, seed_b = policy_stream(20260924, 0, 0, "randomization.policy.visibility_km")
    assert seed_a == seed_b and 1 <= seed_a <= MAX_SEED
    assert a.uniform() == b.uniform()
    other_leaf = policy_stream(20260924, 0, 0, "randomization.policy.cloud_cover")[1]
    other_draw = policy_stream(20260924, 1, 0, "randomization.policy.visibility_km")[1]
    other_attempt = policy_stream(20260924, 0, 1, "randomization.policy.visibility_km")[1]
    other_seed = policy_stream(20260925, 0, 0, "randomization.policy.visibility_km")[1]
    assert len({seed_a, other_leaf, other_draw, other_attempt, other_seed}) == 5


def test_draws_are_recorded_with_the_contracts_detail_and_differ_by_draw_index():
    first, second = _spec(POLICY), _spec(POLICY)
    sample_randomization(first, draw_index=0)
    sample_randomization(second, draw_index=1)
    q = first.randomization.visibility_km
    assert q.source is Source.SAMPLED
    assert set(q.detail) == {"policy", "distribution", "seed", "draw_index"}
    assert q.detail["policy"] == "randomization.policy.visibility_km"
    assert q.detail["distribution"] == POLICY["visibility_km"]
    assert q.detail["draw_index"] == 0
    assert 1 <= q.detail["seed"] <= MAX_SEED
    assert second.randomization.visibility_km.detail["draw_index"] == 1
    assert second.randomization.visibility_km.value != q.value
    assert second.randomization.visibility_km.detail["seed"] != q.detail["seed"]
    # Two draws of the same index are the same draw.
    again = _spec(POLICY)
    sample_randomization(again, draw_index=0)
    assert again.to_dict() == first.to_dict()
    # The card names the derivation and the campaign seed.
    record = card_block(first)["policy_draws"]
    assert record["draw_index"] == 0 and "SeedSequence" in record["seed_derivation"]
    assert record["campaign_seed"] == int(first.randomization.seed.value)


# -- the whole policy ---------------------------------------------------------

def test_the_contract_policy_draws_every_leaf_validates_and_round_trips(tmp_path):
    spec = _spec(POLICY)
    sample_randomization(spec)
    block = spec.randomization
    for name in ("visibility_km", "cloud_cover", "precipitation", "hour_local",
                 "location", "traffic_count", "livery", "fog_density", "hour_utc",
                 "year", "day_of_year"):
        assert getattr(block, name).source is Source.SAMPLED, name
    for name in ("wind_speed", "turbulence", "surface", "aircraft", "weather_date",
                 "latitude", "longitude", "terrain_elevation"):
        assert getattr(spec, name).source is Source.SAMPLED, name
    assert str(spec.aircraft.value) in ("A320", "B747")
    assert spec.turbulence.detail["W20_kt"] in (0.0, 15.0, 30.0, 45.0)
    assert 1.0 <= float(block.visibility_km.value) <= 80.0
    assert float(block.fog_density.value) == pytest.approx(
        wv.fog_extinction_per_m(float(block.visibility_km.value)), rel=1e-5)
    # hour_utc follows hour_local by the documented local-mean-time rule.
    expected_utc = (float(block.hour_local.value)
                    - float(spec.longitude.value) / 15.0) % 24.0
    assert float(block.hour_utc.value) == pytest.approx(expected_utc, abs=1e-3)
    # The sampled date is the block's year and day.
    from datetime import date
    day = date.fromisoformat(str(spec.weather_date.value))
    assert int(block.year.value) == day.year
    assert int(block.day_of_year.value) == day.timetuple().tm_yday
    # The fixed scalar set the range field; the sun honours it.
    assert float(block.sun_elevation_min_deg.value) == 2.0
    assert block.sun_elevation_min_deg.source is Source.DERIVED
    assert float(block.sun_elevation_deg.value) >= 2.0
    # The location moved the place to a bake in the chosen range.
    from core.terrain.glo30 import LOCATIONS
    assert str(block.location.value) in LOCATIONS
    assert float(spec.latitude.value) == LOCATIONS[str(block.location.value)].origin_lat
    # Cameras: the drawn preset re-defaulted the placement, the lens is
    # in range, the offset jitter kept its base.
    camera = spec.cameras[0]
    assert camera.preset.source is Source.SAMPLED
    assert 24.0 <= float(camera.focal_length_mm.value) <= 400.0
    if str(camera.preset.value) in ("chase", "wingman"):
        assert "randomization_base" in camera.offset_forward_m.detail
    assert validate(spec).ok
    # Idempotent through YAML, and the digest is stable.
    path = spec.write(tmp_path / "policy.yaml")
    reread = ScenarioSpec.read(path)
    assert reread.digest() == spec.digest()
    sample_randomization(reread)
    assert reread.to_dict() == spec.to_dict()
    # The card carries one entry per sampled leaf, the policy, the draw
    # record and the full look block; the four Phase 10 look keys stand.
    card = card_block(spec)
    for name in ("visibility_km", "cloud_cover", "precipitation", "hour_local",
                 "location", "traffic_count", "wind_speed_kt", "turbulence",
                 "surface", "aircraft", "weather_date", "policy", "policy_draws"):
        assert name in card, name
    assert card["policy"] == POLICY
    look = card["look"]
    assert look["sun_elev"] == card["sun_elevation_deg"]
    assert look["fog_density"] == card["fog_density"]
    assert look["fog_extinction_per_m"] == pytest.approx(look["fog_density"], rel=1e-6)
    assert look["visibility_km"] == pytest.approx(float(block.visibility_km.value), abs=1e-3)
    assert look["cloud_drift_mps"] == pytest.approx(float(spec.wind_speed.value) * 0.514444, abs=1e-3)
    assert set(look["ev100"]) == {"camera0"}
    assert "precipitation_particles" in look["not_claimed"]
    # The render table shows the sampled rows with their source.
    assert "sampled" in spec.render_table()


def test_a_policy_switches_a_defaulted_block_on_and_refuses_a_stated_off():
    spec = _spec({"cloud_cover": {"beta": [2, 2]}}, seed=None)
    assert not spec.randomization.is_enabled()
    sample_randomization(spec)
    assert spec.randomization.is_enabled()
    assert spec.randomization.enabled.source is Source.DERIVED
    off = _spec({"cloud_cover": {"beta": [2, 2]}})
    off.set("randomization.enabled", False, frm="the user said off")
    with pytest.raises(RandomizationError) as caught:
        sample_randomization(off)
    assert caught.value.constraint == "randomization.policy"


# -- refusals: counted, re-drawn, capped ---------------------------------------

def test_a_refused_draw_is_counted_and_re_drawn_never_dropped():
    """A c172p cannot trim at 280 kt: every c172p draw is refused by
    validate() (envelope.trim_feasible), recorded with its values and
    re-drawn; the committed spec carries a B747 and the count."""
    spec = _spec({"aircraft": {"choice": ["c172p", "B747"], "weights": [3, 1]}},
                 seed=1)
    sample_randomization(spec)
    record = spec.randomization.policy_draws.value
    assert str(spec.aircraft.value) == "B747"
    assert record["attempts"] == len(record["refused"]) + 1
    assert record["refused"], "the seed must produce at least one refused draw"
    for refusal in record["refused"]:
        assert set(refusal) >= {"draw_index", "attempt", "refusal_name",
                                "sampled_values"}
        assert refusal["refusal_name"] == "envelope.trim_feasible"
        assert refusal["sampled_values"]["aircraft"] == "c172p"
        assert refusal["draw_index"] == 0
    assert [r["attempt"] for r in record["refused"]] == list(range(len(record["refused"])))
    assert record["max_attempts"] == MAX_POLICY_ATTEMPTS == 20
    assert card_block(spec)["policy_draws"]["refused"] == record["refused"]


def test_an_exhausted_slot_refuses_infeasible_by_name_with_every_refusal_and_moves_nothing():
    spec = _spec({"aircraft": {"choice": ["c172p"]}}, seed=3)
    before = spec.to_dict()
    with pytest.raises(RandomizationError) as caught:
        sample_randomization(spec)
    assert caught.value.constraint == "randomization.infeasible"
    assert "20" in caught.value.message
    detail = caught.value.detail
    assert detail["refused"] == detail["draws"] == MAX_POLICY_ATTEMPTS == 20
    assert len(detail["refusals"]) == 20
    assert {r["refusal_name"] for r in detail["refusals"]} == {"envelope.trim_feasible"}
    assert [r["attempt"] for r in detail["refusals"]] == list(range(20))
    assert spec.to_dict() == before                  # a refusal is not a run
    assert spec.randomization.policy_draws.value is None


def test_a_draw_below_the_sun_floor_is_a_refused_draw_not_a_crash():
    """hour_local at night: the Phase 10 daylight rule refuses each
    draw by its own name inside the loop; the record says so."""
    spec = _spec({"hour_local": {"uniform": [0.0, 2.0]}})
    spec.set("latitude", 51.5, frm="test")
    spec.set("longitude", 0.0, frm="test")
    with pytest.raises(RandomizationError) as caught:
        sample_randomization(spec)
    assert caught.value.constraint == "randomization.infeasible"
    assert {r["refusal_name"] for r in caught.value.detail["refusals"]} == \
        {"randomization.time_of_day"}


# -- gates, locations, stated fields, unknown leaves -------------------------

def test_a_gate_shut_takes_the_first_choice_and_records_it_open_draws():
    shut = _spec({"cloud_cover": {"uniform": [0.0, 0.1]},
                  "precipitation": {"choice": ["none", "rain"], "weights": [0, 1],
                                    "gated_by": "cloud_cover > 0.6"}})
    sample_randomization(shut)
    assert str(shut.randomization.precipitation.value) == "none"
    assert shut.randomization.precipitation.detail["gated"] == "cloud_cover > 0.6"
    open_ = _spec({"cloud_cover": {"uniform": [0.9, 1.0]},
                   "precipitation": {"choice": ["none", "rain"], "weights": [0, 1],
                                     "gated_by": "cloud_cover > 0.6"}})
    sample_randomization(open_)
    assert str(open_.randomization.precipitation.value) == "rain"
    assert "gated" not in open_.randomization.precipitation.detail
    assert render_look(open_)["wetness"] == 1.0
    assert render_look(open_)["visibility_km"] <= 10.0
    undrawn = _spec({"precipitation": {"choice": ["none", "rain"],
                                       "gated_by": "cloud_cover > 0.6"}})
    with pytest.raises(RandomizationError) as caught:
        sample_randomization(undrawn)
    assert caught.value.constraint == "randomization.policy"
    assert "cloud_cover" in caught.value.message


def test_a_range_with_no_bake_refuses_location_by_name_and_a_stated_place_is_kept():
    for names in (["rockies"], ["cascades"], ["atlantis"], ["alps", "rockies"]):
        spec = _spec({"location": {"choice": names}})
        with pytest.raises(RandomizationError) as caught:
            sample_randomization(spec)
        assert caught.value.constraint == "randomization.location", names
    stated = _spec({"location": {"choice": ["alps"]}})
    stated.set("latitude", 46.0, frm="stated")
    with pytest.raises(RandomizationError) as caught:
        sample_randomization(stated)
    assert caught.value.constraint == "randomization.policy"
    assert "latitude" in caught.value.message
    alps = _spec({"location": {"choice": ["alps"]}})
    sample_randomization(alps)
    assert str(alps.randomization.location.value) == "matterhorn"
    assert float(alps.terrain_elevation.value) == 1860.0
    assert alps.terrain_elevation.source is Source.SAMPLED


def test_a_leaf_over_a_stated_field_an_unknown_leaf_and_a_bad_fixed_value_refuse_by_name():
    stated = _spec({"aircraft": {"choice": ["A320"]}},
                   prompt="fly the 747 at 10000 ft and 280 kt for 60 seconds")
    with pytest.raises(RandomizationError) as caught:
        sample_randomization(stated)
    assert caught.value.constraint == "randomization.policy"
    assert "user-stated" in caught.value.message
    for policy in ({"moon_phase": {"choice": ["full"]}},
                   {"seed": 4},
                   {"hour_local": {"beta": [2, 2]}},
                   {"precipitation": {"choice": ["hail"]}},
                   {"cameras": {"zoom": {"uniform": [1, 2]}}}):
        with pytest.raises(RandomizationError) as caught:
            sample_randomization(_spec(policy))
        assert caught.value.constraint == "randomization.policy", policy
    fixed = _spec({"sun_elevation_min_deg": 12, "cloud_cover": {"beta": [2, 2]}})
    sample_randomization(fixed)
    assert float(fixed.randomization.sun_elevation_min_deg.value) == 12.0
    assert float(fixed.randomization.sun_elevation_deg.value) >= 12.0


def test_the_hour_window_choice_draws_inside_the_named_window():
    spec = _spec({"hour_local": {"choice": ["dawn", "dusk"]}})
    sample_randomization(spec)
    hour = float(spec.randomization.hour_local.value)
    assert any(lo <= hour <= hi for lo, hi in (HOUR_WINDOWS["dawn"],
                                                HOUR_WINDOWS["dusk"]))
    assert "window" in spec.randomization.hour_local.frm


def test_the_camera_group_applies_to_every_camera_and_never_moves_a_stated_preset():
    spec = _spec({"cameras": {"preset": {"choice": ["tower"]},
                              "focal_length_mm": {"uniform": [100, 100]}}})
    spec.cameras.append(CameraSpec.defaulted(camera_id="second", preset="chase",
                                             aircraft="B747", terrain_elevation_m=0.0))
    sample_randomization(spec)
    for camera in spec.cameras:
        assert str(camera.preset.value) == "tower"
        assert float(camera.focal_length_mm.value) == 100.0
        # The tower's own default placement (the Phase 10 jitter then
        # moved it by its usual metre, from that base).
        assert camera.position_north_m.detail["randomization_base"] == 900.0
        assert abs(float(camera.position_north_m.value) - 900.0) <= 1.0
    # A named view keeps its preset (the Phase 10 jitter's rule: skipped
    # and noted, never moved); the lens still varies.
    stated = _spec({"cameras": {"preset": {"choice": ["tower"]},
                                "focal_length_mm": {"uniform": [100, 100]}}},
                   prompt="chase view of the a320 at 10000 ft and 280 kt for 60 seconds",
                   camera=False)
    sample_randomization(stated)
    camera, = stated.cameras
    assert str(camera.preset.value) == "chase" and camera.preset.source is Source.INFERRED
    assert float(camera.focal_length_mm.value) == 100.0
    assert any("preset" in n and "not drawn" in n for n in stated.notes)


def test_every_leaf_the_sampler_knows_is_of_a_documented_kind():
    for table in (POLICY_LEAVES, POLICY_CAMERA_LEAVES):
        for name, entry in table.items():
            assert entry["kind"] in ("number", "integer", "word", "date"), name
            assert entry["forms"], name
            assert set(entry["forms"]) <= {"choice", "uniform", "loguniform",
                                           "normal", "lognormal", "beta",
                                           "weibull", "poisson", "uniform_dates"}


# -- the realised distribution ------------------------------------------------

def _fake_run(tmp_path, name, block, frames):
    run = tmp_path / name
    run.mkdir()
    (run / "capture_manifest.json").write_text(json.dumps({
        "manifest_version": 6, "randomization": block,
        "frames": [{"index": i} for i in range(frames)]}), encoding="utf-8")
    return run


def test_realised_distribution_histograms_frames_states_coverage_and_counts_refusals(tmp_path):
    policy = {"aircraft": {"choice": ["A320", "B747", "c172p"]},
              "visibility_km": {"uniform": [0, 80]},
              "location": {"choice": ["alps", "yosemite"]}}
    runs = [
        _fake_run(tmp_path, "a", {"aircraft": "A320", "visibility_km": 5.0,
                                  "location": "matterhorn", "policy": policy,
                                  "policy_draws": {"refused": [
                                      {"refusal_name": "envelope.trim_feasible"},
                                      {"refusal_name": "randomization.time_of_day"}]}}, 4),
        _fake_run(tmp_path, "b", {"aircraft": "B747", "visibility_km": 75.0,
                                  "location": "matterhorn",
                                  "policy_draws": {"refused": [
                                      {"refusal_name": "envelope.trim_feasible"}]}}, 6),
        _fake_run(tmp_path, "c", {"seed": 1}, 3),            # no policy: Phase 10 run
        tmp_path / "missing",                                  # tolerated
    ]
    realised = realised_distribution(runs, k=1)
    assert realised["runs"] == 3 and realised["frames"] == 13
    aircraft = realised["fields"]["aircraft"]
    assert aircraft["histogram"] == {"A320": 4, "B747": 6, "c172p": 0}
    assert aircraft["coverage"] == pytest.approx(2 / 3, abs=1e-3)
    visibility = realised["fields"]["visibility_km"]
    assert visibility["bins"] == 8 and sum(visibility["histogram"].values()) == 10
    assert visibility["coverage"] == pytest.approx(2 / 8, abs=1e-3)
    location = realised["fields"]["location"]
    assert set(location["histogram"]) == {"matterhorn", "yosemite"}
    assert location["coverage"] == 0.5
    assert realised["coverage"] == pytest.approx((2 / 3 + 2 / 8 + 0.5) / 3, abs=1e-3)
    assert realised["refusals"] == {"envelope.trim_feasible": 2,
                                    "randomization.time_of_day": 1}
    # k raises the bar: a bin needs k frames to count.
    assert realised_distribution(runs, k=5)["fields"]["aircraft"]["coverage"] == \
        pytest.approx(1 / 3, abs=1e-3)
    # The picture.
    from core.scene.realised_plot import draw_realised, main

    png = draw_realised(realised, tmp_path / "realised.png")
    from PIL import Image
    with Image.open(png) as image:
        assert image.size[0] >= 640 and image.size[1] > 3 * 100
    assert main([str(runs[0]), str(runs[1]), "--out", str(tmp_path / "cli.png"),
                 "--json", str(tmp_path / "cli.json")]) == 0
    written = json.loads((tmp_path / "cli.json").read_text(encoding="utf-8"))
    assert written["fields"]["aircraft"]["histogram"]["A320"] == 4


def test_realised_distribution_reads_the_sampler_s_own_card_blocks():
    """The record the sampler writes is what the campaign reads back:
    two draws of the contract policy, binned by the requested leaves."""
    blocks = []
    for index in range(2):
        spec = _spec(POLICY)
        sample_randomization(spec, draw_index=index)
        blocks.append({"randomization": card_block(spec), "frames": 5})
    realised = realised_distribution(blocks)
    assert realised["frames"] == 10
    assert set(realised["fields"]) >= {"aircraft", "visibility_km", "cloud_cover",
                                       "location", "wind_speed_kt", "turbulence"}
    assert realised["fields"]["aircraft"]["requested"] == POLICY["aircraft"]
    assert set(realised["fields"]["location"]["histogram"]) >= {"matterhorn",
                                                                "yosemite",
                                                                "flint_hills"}
    assert 0.0 < realised["coverage"] <= 1.0
