"""W3, precipitation: Marshall-Palmer with a FITTED Lambda (the closure
measured), D0, the Atlas 1973 fall speed (v(2 mm) = 6.5 m/s), the
relative streak (linear in the shutter, inverse in the range, measured),
the Atlas 1953 extinction reconciled with the Koschmieder fog row (counted
once), the MIL-HDBK-310 bound refused by name, the spec field
(absent-canonical), the card's look.precipitation block, and the registry
pair measured silent on a 1 s flight (a bounded invariance)."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from core.scene import precipitation as p
from core.scene import weather_visuals as wv

REPO = Path(__file__).resolve().parents[1]


def test_the_atlas_fall_speed_meets_the_gunn_kinzer_anchor():
    assert p.terminal_velocity_mps(2.0) == pytest.approx(9.65 - 10.3 * math.exp(-1.2))
    assert p.terminal_velocity_mps(2.0) == pytest.approx(6.5, abs=0.05)
    assert p.terminal_velocity_mps(1.0) < p.terminal_velocity_mps(2.0) < p.terminal_velocity_mps(4.0)


def test_mp_lambda_over_predicts_the_rate_and_the_fitted_lambda_closes():
    """The closed form re-implemented from the docstring: R(Lambda) = 6 pi
    1e-4 N0 6 (a / L^4 - b / (L + c)^4), and the clamped rate against a
    quadrature of max(v, 0) written here."""
    def closed(lam):
        return 6 * math.pi * 1e-4 * 8000.0 * 6 * (9.65 / lam ** 4 - 10.3 / (lam + 0.6) ** 4)

    def quadrature(lam, top=40.0, steps=40000):
        h = top / steps
        total = 0.0
        for i in range(steps):
            d = (i + 0.5) * h
            total += d ** 3 * max(0.0, 9.65 - 10.3 * math.exp(-0.6 * d)) * 8000.0 * math.exp(-lam * d)
        return 6 * math.pi * 1e-4 * total * h

    assert p.rate_for_lambda(3.0, clamp=False) == pytest.approx(closed(3.0))
    assert p.rate_for_lambda(3.0) == pytest.approx(quadrature(3.0), rel=1e-6)
    assert p.rate_for_lambda(6.0) == pytest.approx(quadrature(6.0), rel=1e-6)
    assert p.mp_lambda(4.0) == pytest.approx(4.1 * 4.0 ** -0.21)
    assert p.rate_for_lambda(p.mp_lambda(4.0)) == pytest.approx(4.73, abs=0.01)   # 18 % over
    for rate in (0.5, 1.0, 4.0, 10.0, 25.0, 48.0, 150.0):
        lam = p.fitted_lambda(rate)
        assert abs(p.rate_for_lambda(lam) - rate) / rate < p.CLOSURE_TOLERANCE
        assert abs(p.rate_for_lambda(lam) - rate) / rate < 1e-9                # measured
        assert lam > p.mp_lambda(rate)              # fewer large drops than MP's own
        # The clamp's share, by the independent quadrature, is what the
        # incomplete-gamma form removed.
        share = (p.rate_for_lambda(lam, clamp=False) - p.rate_for_lambda(lam)) / p.rate_for_lambda(lam)
        assert -share == pytest.approx(p.negative_speed_fraction(lam), rel=1e-3)
        assert p.negative_speed_fraction(lam) < 1e-4
    numbers = p.rain(4.0)
    assert numbers["closure"] < 1e-9 and numbers["lambda_mp_per_mm"] == pytest.approx(p.mp_lambda(4.0))
    assert numbers["d0_mm"] == pytest.approx(3.67 / numbers["lambda_fitted_per_mm"])
    assert 4.1 <= numbers["v_t_mps"] <= 4.6                 # the blueprint's v(D0) band
    assert numbers["number_density_per_m3"] == pytest.approx(8000.0 / numbers["lambda_fitted_per_mm"])


def test_the_streak_is_linear_in_the_shutter_and_inverse_in_the_range():
    v = (3.0, 4.5, -60.0)
    base = p.streak_vector_px(v, 1 / 500, 1500.0, 1500.0, 20.0)
    assert base[2] == pytest.approx(1 / 500 * 1500.0 * math.hypot(3.0, 4.5) / 20.0)
    for factor in (2.0, 3.0, 10.0):
        longer = p.streak_vector_px(v, factor / 500, 1500.0, 1500.0, 20.0)
        assert longer[2] == pytest.approx(factor * base[2], rel=1e-12)
        farther = p.streak_vector_px(v, 1 / 500, 1500.0, 1500.0, 20.0 * factor)
        assert farther[2] == pytest.approx(base[2] / factor, rel=1e-12)
    # Off the axis the along-axis motion streaks radially (the focus of expansion).
    off = p.streak_vector_px((0.0, 0.0, -60.0), 1 / 500, 1500.0, 1500.0, 20.0, x_m=2.0)
    assert off[0] == pytest.approx(1 / 500 * 1500.0 * (2.0 * 60.0) / 400.0) and off[1] == 0.0
    with pytest.raises(ValueError):
        p.streak_vector_px(v, 1 / 500, 1500.0, 1500.0, 0.0)


def test_the_relative_velocity_is_drop_minus_camera_in_camera_axes():
    axes = ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0))  # right=E, down, forward=N
    rel = p.relative_velocity_camera((0.0, 0.0, -4.5), (0.0, 50.0, 0.0), axes)
    assert rel == pytest.approx((0.0, 4.5, -50.0))
    stationary = p.preset_streaks("ground", 1 / 500, 1500.0, 1500.0, 50.0, 4.5)
    assert stationary["relative_px"] == stationary["stationary_px"]        # a fixed camera
    abeam = p.preset_streaks("wingman", 1 / 500, 1500.0, 1500.0, 50.0, 4.5)
    assert abeam["relative_px"] == pytest.approx(1 / 500 * 1500.0 * math.hypot(50.0, 4.5) / 20.0,
                                                 abs=1e-3)
    along = p.preset_streaks("chase", 1 / 500, 1500.0, 1500.0, 50.0, 4.5)
    assert along["relative_px"] == pytest.approx(along["stationary_px"])     # on the axis


def test_the_extinction_is_reconciled_with_the_fog_row_and_counted_once():
    lam = p.fitted_lambda(10.0)
    sigma = p.extinction_per_m(lam)
    assert sigma == pytest.approx(math.pi * 8000.0 / lam ** 3 * 1e-6)
    clear = p.reconcile_extinction(60.0, sigma)             # a clear day meets the rain
    assert clear["fog_extinction_per_m"] == pytest.approx(sigma) and clear["limited_by"] == "rain"
    foggy = p.reconcile_extinction(0.5, sigma)              # a fog already denser than the rain
    assert foggy["fog_extinction_per_m"] == pytest.approx(3.912 / 500.0)
    for visibility in (0.5, 2.0, 60.0):
        row = p.reconcile_extinction(visibility, sigma)
        assert row["fog_extinction_per_m"] == pytest.approx(max(3.912 / (1000 * visibility), sigma))
        assert row["fog_extinction_per_m"] < 3.912 / (1000 * visibility) + sigma   # never summed
    # The look table: a rate replaces the word's floor with the rain's own.
    look = wv.look_block({"visibility_km": 60.0, "precipitation_rate_mmh": 10.0})
    assert look["precipitation"] == "rain" and look["wetness"] == 1.0
    assert look["fog_extinction_per_m"] == pytest.approx(sigma, rel=1e-5)
    assert look["rain_extinction_per_m"] == pytest.approx(sigma, rel=1e-5)
    assert look["visibility_km"] == pytest.approx(3.912 / (1000 * sigma), rel=1e-3)
    assert wv.look_block({"visibility_km": 0.5, "precipitation_rate_mmh": 10.0})[
        "fog_extinction_per_m"] == pytest.approx(3.912 / 500.0, rel=1e-5)


def test_the_rate_is_bounded_and_refused_by_name():
    assert p.rate_problem(None) is None and p.rate_problem(4.0) is None
    assert p.RAIN_RATE_MAX_MMH == pytest.approx(1872.0)
    for bad in (0.0, -1.0, float("nan"), "lots", True, 2000.0):
        assert p.rate_problem(bad), bad
    with pytest.raises(p.PrecipitationError) as caught:
        p.rain(0.0)
    assert caught.value.constraint == "look.precipitation_rate"
    assert p.rain(60.0)["beyond_operational_1pct"] and not p.rain(40.0)["beyond_operational_1pct"]


def _spec(rate=None):
    from core.nl.compiler import compile_prompt

    spec = compile_prompt("fly the c172p at 1500 m and 100 kt for 1 seconds")
    spec.set("hold_state", False, frm="test")
    if rate is not None:
        spec.set("precipitation_rate_mmh", rate, frm="test")
    return spec


def test_the_rate_is_absent_canonical_behind_the_front_door_and_validated(tmp_path):
    from core.messages import explain, is_catalogued
    from core.scenario.spec import ScenarioSpec
    from core.scenario.validate import validate
    from tests.test_registry import EXAMPLE_DIGESTS

    for path, digest in EXAMPLE_DIGESTS.items():
        assert ScenarioSpec.read(REPO / path).digest() == digest, path
    plain = _spec()
    assert "precipitation_rate_mmh" not in plain.to_dict()["environment"]
    wet = _spec(4.0)
    assert wet.to_dict()["environment"]["precipitation_rate_mmh"]["value"] == 4.0
    assert wet.digest() != plain.digest()
    again = ScenarioSpec.read(wet.write(tmp_path / "wet.yaml"))
    assert again.digest() == wet.digest() and again.precipitation_rate_mmh.value == 4.0
    assert "precipitation rate mmh" in wet.render_table()
    refused = validate(_spec(5000.0), check_feasibility=False).violations
    assert [v.constraint for v in refused] == ["look.precipitation_rate"]
    assert is_catalogued("look.precipitation_rate")
    assert "5000" in explain(refused[0])["sentence"]
    assert validate(wet, check_feasibility=False).ok


def test_the_card_carries_look_precipitation_in_its_fixed_key_order():
    from core.scenario.card import world_look_card_block

    block = world_look_card_block(_spec(4.0))
    assert list(block) == ["precipitation", "cloud_drift"]
    rain = block["precipitation"]
    assert tuple(rain) == p.CARD_KEYS
    assert rain["rate_mmh"] == 4.0 and rain["lambda"] == pytest.approx(p.fitted_lambda(4.0), abs=1e-6)
    (camera, streaks), = rain["streak_px"].items()
    assert camera == "camera0" and streaks["stationary_px"] > 0.0
    assert block["cloud_drift"]["source"] == "wind at cloud base"


@pytest.mark.timeout(120)
def test_the_registry_pair_is_a_bounded_invariance_measured_silent():
    """A look variable moves the render, not the flight: the pair of 4 mm/h
    against unstated leaves every registered channel where it was."""
    from core.record_null import run_null_pair
    from core.registry import REGISTRY

    entry = REGISTRY.get("environment.precipitation_rate_mmh")
    assert entry.null_value is None and entry.unit == "mm/h"
    pair = run_null_pair(_spec(4.0), "environment.precipitation_rate_mmh")
    assert pair.verdict == "silent"
    assert pair.with_output_digest == pair.without_output_digest
    assert pair.with_spec_digest != pair.without_spec_digest
