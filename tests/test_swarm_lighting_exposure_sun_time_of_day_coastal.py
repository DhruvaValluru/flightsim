"""Source-level checks for the coastal sun / time-of-day lane (Mac).

These check the bake's arithmetic, its agreement with the repo's own light
model and the pixel gate's maths on synthetic images. They are NOT a render
or pixel result: that is measured on the Windows laptop (see the lane's
INTEGRATION.md).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm" / "lanes" / "lighting_exposure" / "sun_time_of_day" / "coastal"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"coastal_tod_{name}", LANE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bake = _load("bake_coastal_sun_tod")
gate = _load("measure_exposure")


@pytest.fixture(scope="module")
def plan():
    return bake.build()


def test_committed_bake_is_reproducible_and_matches_provenance(plan, tmp_path):
    digests = bake.write(tmp_path)
    recorded = {g["file"]: g["sha256"]
                for g in json.loads((LANE / "PROVENANCE.json").read_text())["generated"]}
    assert set(recorded) == set(digests)
    for name, digest in digests.items():
        assert hashlib.sha256((LANE / name).read_bytes()).hexdigest() == digest, name
        assert recorded[name] == digest, name
    assert json.loads((LANE / "coastal_sun_tod.json").read_text()) == json.loads(json.dumps(plan))


def test_provenance_ships_nothing_vendored_and_no_bad_licence():
    text = (LANE / "PROVENANCE.json").read_text()
    provenance = json.loads(text)
    assert provenance["vendored"] == [] and provenance["label"] == "visual-only"
    for entry in provenance["generated"] + provenance["sources"]:
        licence = entry["licence"].lower()
        assert "non-commercial" not in licence and "gpl" not in licence and "-nc" not in licence


def test_constants_agree_with_the_repo():
    from core.scene import beauty_look
    from core.sky import plan as sky_plan
    assert bake.METER_C == beauty_look.METER_CALIBRATION_C
    assert bake.IES_CLEAR_DIFFUSE_KLX == tuple(beauty_look.IES_CLEAR_DIFFUSE_KLX)
    assert bake.SUN_OUTER_SPACE_LUX == sky_plan.SUN_ILLUMINANCE_LUX
    assert bake.meter_ev100(12345.0) == pytest.approx(beauty_look.meter_ev100(12345.0))


def test_rows_are_physically_ordered(plan):
    rows = plan["rows"]
    for lo, hi in zip(rows, rows[1:]):
        for key in ("target_ev100", "sun_direct_normal_lux", "sky_diffuse_horizontal_lux",
                    "sun_colour_temperature_k", "sun_to_sky_ratio"):
            assert hi[key] > lo[key], (key, lo["sun_elevation_deg"])
    for r in rows:
        # sea haze dims the beam and brightens the sky against the repo's clear day
        assert r["sun_direct_normal_lux"] < r["sun_direct_normal_lux_repo_clear"]
        assert 0.0 <= r["repo_model_meter_ev100"] - r["meter_ev100"] < 0.3
        assert 1500 <= r["sun_colour_temperature_k"] <= 5800
        tint = r["sun_linear_srgb_tint"]
        assert tint[0] == 1.0 and tint[0] >= tint[1] >= tint[2] >= 0.0
        # the meter puts a flat 18% card at the same scene value whatever the sun
        assert r["expected_scene_linear"]["grey_18_flat"] == pytest.approx(0.1194, abs=0.02)
        assert r["expected_scene_linear"]["white_sun_facing"] <= bake.WHITE_SUN_FACING_CEILING + 1e-6
        assert 0.0 <= r["white_protect_ev"] <= bake.WHITE_PROTECT_MAX_EV


def test_haze_visibility_matches_the_sibling_lanes_proposal(plan):
    # aircraft_exterior coastal lanes proposed 15 km sea haze and a 12 deg sun
    assert plan["constants"]["sea_haze_visibility_km"] == pytest.approx(15.0, abs=1.5)
    assert plan["nominal"]["sun_elevation_deg"] == 12.0


def test_lookup_interpolates_and_clamps(plan):
    rows = {r["sun_elevation_deg"]: r for r in plan["rows"]}
    assert bake.lookup(plan, 12.0)["target_ev100"] == pytest.approx(rows[12.0]["target_ev100"])
    mid = bake.lookup(plan, 13.5)["target_ev100"]
    assert mid == pytest.approx((rows[12.0]["target_ev100"] + rows[15.0]["target_ev100"]) / 2)
    assert bake.lookup(plan, 85.0)["target_ev100"] == rows[60.0]["target_ev100"]
    assert bake.lookup(plan, -3.0)["target_ev100"] == rows[2.0]["target_ev100"]
    # no step between neighbouring degrees is as large as the gate
    for tenth in range(20, 600):
        a = bake.lookup(plan, tenth / 10)["target_ev100"]
        b = bake.lookup(plan, tenth / 10 + 1.0)["target_ev100"]
        assert abs(b - a) < bake.GATE_EV + 0.05


def test_table_differs_from_the_stepped_bands_where_it_claims_to(plan):
    from core.scene import beauty_look
    worst = max(abs(beauty_look.ev100_band(e)[0] - bake.lookup(plan, e)["target_ev100"])
                for e in (8.0, 14.9, 15.0, 24.9))
    assert worst > bake.GATE_EV   # the reason the lane exists


def test_clock_time_follows_the_repo_sun_position(plan):
    from core.scenario import solar
    site = bake.SITE
    utc = 18.0 - site["utc_offset_h"]
    got = bake.sun_for_time(plan, site["latitude_deg"], site["longitude_deg"], site["year"],
                            site["day_of_year"] + int(utc // 24), utc % 24)
    pos = solar.solar_position(site["latitude_deg"], site["longitude_deg"], site["year"],
                               site["day_of_year"] + int(utc // 24), utc % 24)
    assert got["sun_elevation_deg"] == pos.elevation_deg
    assert 240.0 < got["sun_azimuth_deg"] < 280.0            # evening sun over the Pacific
    assert got["target_ev100"] == pytest.approx(bake.lookup(plan, pos.elevation_deg)["target_ev100"])
    # night: the table declines, the band stands
    assert bake.sun_for_time(plan, site["latitude_deg"], site["longitude_deg"],
                             site["year"], site["day_of_year"], 9.0) is None
    curve = bake.day_curve(plan)
    assert max(r["sun_elevation_deg"] for r in curve) == pytest.approx(52.0, abs=2.0)
    assert plan["nominal"]["site_evening_local_hour"] in [r["local_hour"] for r in curve]


def test_sun_colour_and_glitter_helpers():
    assert bake.sun_colour(90.0, aod_500=0.0)["cct_k"] < bake.SUN_PLANCK_K
    assert bake.fresnel_unpolarised(0.0) == pytest.approx(0.0211, abs=0.001)
    assert bake.fresnel_unpolarised(89.9) > 0.9
    assert bake.glitter_peak_luminance(37721.0, 12.0) > 50 * 1.2 * 2 ** 12.8 / 10


def _frame(scale: float, clip_rows: int = 0) -> Image.Image:
    rng = np.random.default_rng(7)
    lin = rng.uniform(0.03, 0.4, size=(120, 160, 1)) * np.ones((1, 1, 3)) * scale
    srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.clip(lin, 0, 1) ** (1 / 2.4) - 0.055)
    data = (np.clip(srgb, 0, 1) * 255).round().astype(np.uint8)
    data[:clip_rows] = 255
    return Image.fromarray(data)


def test_gate_arithmetic_on_synthetic_frames():
    base = _frame(1.0)
    half_stop_darker = _frame(2 ** -0.5)
    good = gate.measure(base, half_stop_darker, baseline_ev100=13.0, target_ev100=13.5)
    assert good["pass"] and abs(good["ev_error_stops"]) < 0.05
    missed = gate.measure(base, base, baseline_ev100=13.0, target_ev100=13.5)
    assert not missed["pass"] and missed["ev_error_stops"] == pytest.approx(0.5, abs=0.05)
    blown = gate.measure(base, _frame(2 ** -0.5, clip_rows=12), 13.0, 13.5)
    assert blown["ev_pass"] and not blown["clip_pass"] and not blown["pass"]
    black = Image.new("RGB", (160, 120))
    assert "refused" in gate.measure(black, black, 13.0, 13.0)
    assert math.isclose(gate.GATE_EV, bake.GATE_EV)
