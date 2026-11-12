"""Source-level checks for the alpine physical-light-units lane (Mac).

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

import pytest

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm" / "lanes" / "lighting_exposure" / "physical_light_units" / "alpine"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"alpine_plu_{name}", LANE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bake = _load("bake_alpine_plu")


@pytest.fixture(scope="module")
def plan():
    return bake.build()


def test_committed_bake_is_reproducible_and_matches_provenance(plan, tmp_path):
    digests = bake.write(tmp_path)
    provenance = json.loads((LANE / "PROVENANCE.json").read_text())
    recorded = {g["file"]: g["sha256"] for g in provenance["generated"]}
    for name, digest in digests.items():
        assert hashlib.sha256((LANE / name).read_bytes()).hexdigest() == digest, name
        assert recorded[name] == digest, name
    assert json.loads((LANE / "alpine_plu.json").read_text()) == json.loads(json.dumps(plan))


def test_provenance_has_no_noncommercial_or_copyleft_shipped(plan):
    provenance = json.loads((LANE / "PROVENANCE.json").read_text())
    assert provenance["vendored"] == []
    for source in provenance["sources"]:
        assert source["name"] and source["licence"]
        assert "non-commercial" not in source["licence"].lower()
        assert "-nc" not in source["licence"].lower()


def test_constants_agree_with_the_repo():
    from core.scene import beauty_look
    assert bake.IES_CLEAR_DIFFUSE_KLX == beauty_look.IES_CLEAR_DIFFUSE_KLX
    assert bake.METER_C == beauty_look.METER_CALIBRATION_C
    assert bake.SUN_OUTER_SPACE_LUX == beauty_look.SUN_OUTER_SPACE_LUX


def test_rows_are_physical(plan):
    assert len(plan["rows"]) == len(bake.ALTITUDES_M) * len(bake.ELEVATIONS_DEG)
    for r in plan["rows"]:
        s = math.sin(math.radians(r["sun_elevation_deg"]))
        assert 0 < r["sun_direct_normal_lux"] < bake.SUN_OUTER_SPACE_LUX
        assert r["global_horizontal_lux"] == pytest.approx(
            r["sun_direct_normal_lux"] * s + r["sky_diffuse_horizontal_lux"], abs=0.2)
        # The incident meter: E = 2.5 * 2^EV100.
        assert 2.5 * 2 ** r["meter_ev100"] == pytest.approx(r["global_horizontal_lux"], rel=2e-3)
        assert 0.0 <= r["snow_protect_ev"] <= bake.SNOW_PROTECT_MAX_EV
        assert r["target_ev100"] == pytest.approx(r["meter_ev100"] + r["snow_protect_ev"], abs=2e-3)
        linear = r["expected_scene_linear"]
        assert linear["snow_in_shade"] < linear["snow_flat_sunlit"] <= linear["snow_sun_facing"]
        if r["snow_protect_ev"] < bake.SNOW_PROTECT_MAX_EV:
            assert linear["snow_sun_facing"] <= bake.SNOW_SUN_FACING_CEILING + 1e-3


def test_thin_air_brightens_the_beam_and_dims_the_sky(plan):
    by = {(r["altitude_m"], r["sun_elevation_deg"]): r for r in plan["rows"]}
    for el in bake.ELEVATIONS_DEG:
        low, high = by[(1600.0, el)], by[(5000.0, el)]
        assert high["sun_direct_normal_lux"] > low["sun_direct_normal_lux"]
        assert high["sky_diffuse_horizontal_lux"] < low["sky_diffuse_horizontal_lux"]
        assert high["sun_to_sky_ratio"] > low["sun_to_sky_ratio"]


def test_exposure_rises_with_the_sun_and_stays_near_the_repo_model(plan):
    from core.scene import beauty_look
    for altitude in bake.ALTITUDES_M:
        rows = [r for r in plan["rows"] if r["altitude_m"] == altitude]
        evs = [r["target_ev100"] for r in rows]
        assert evs == sorted(evs)
        for r in rows:
            repo = beauty_look.meter_ev100(beauty_look.clear_sky_horizontal_lux(
                r["sun_elevation_deg"], altitude))
            assert r["repo_model_meter_ev100"] == pytest.approx(repo, abs=2e-3)
            # The thin-air sky correction alone stays inside the gate from 15 deg
            # up; below that it does not (0.32 EV at 5000 m, 10 deg), which is
            # why the low-sun rows need the Windows probe before they are trusted.
            if r["sun_elevation_deg"] >= 15.0:
                assert abs(r["meter_ev100"] - repo) < bake.GATE_EV
            # And the table stays inside the repo's own guard on its bands.
            band, _ = beauty_look.ev100_band(r["sun_elevation_deg"])
            assert abs(r["target_ev100"] - band) <= beauty_look.EV100_METER_TOLERANCE_STOPS


def test_lookup_interpolates_and_clamps(plan):
    exact = bake.lookup(plan, 5000.0, 30.0)
    assert exact["target_ev100"] == pytest.approx(plan["nominal"]["target_ev100"], abs=1e-3)
    mid = bake.lookup(plan, 5000.0, 35.0)
    lo, hi = bake.lookup(plan, 5000.0, 30.0), bake.lookup(plan, 5000.0, 40.0)
    assert mid["target_ev100"] == pytest.approx((lo["target_ev100"] + hi["target_ev100"]) / 2, abs=1e-6)
    assert bake.lookup(plan, 9000.0, 89.0) == bake.lookup(plan, 5000.0, 67.0)
    assert bake.lookup(plan, 0.0, -5.0) == bake.lookup(plan, 1600.0, 2.0)


# --- the pixel gate's arithmetic, on synthetic images only -----------------

np = pytest.importorskip("numpy")
PIL_Image = pytest.importorskip("PIL.Image")


def _frame(stops: float, clip_rows: int = 0):
    """A linear ramp (0.01..0.6) darkened by ``stops``, sRGB-encoded."""
    ramp = np.tile(np.linspace(0.01, 0.6, 256), (64, 1)) * 2.0 ** stops
    srgb = np.where(ramp <= 0.0031308, ramp * 12.92, 1.055 * np.clip(ramp, 0, 1) ** (1 / 2.4) - 0.055)
    data = np.repeat((np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8)[:, :, None], 3, axis=2)
    data[:clip_rows] = 255
    return PIL_Image.fromarray(data)


def test_gate_measures_a_known_shift_and_passes_inside_the_gate():
    gate = _load("measure_exposure")
    # Baseline at EV 15.0, candidate rendered half a stop darker (EV 15.5).
    result = gate.measure(_frame(0.0, clip_rows=4), _frame(-0.5), 15.0, 15.5)
    assert result["measured_shift_stops"] == pytest.approx(-0.5, abs=0.03)
    assert abs(result["ev_error_stops"]) < 0.05 and result["pass"]


def test_gate_fails_a_wrong_exposure_and_a_clipping_regression():
    gate = _load("measure_exposure")
    # The plumbing did nothing: the frame did not move but the table asked for -0.5.
    assert not gate.measure(_frame(0.0), _frame(0.0), 15.0, 15.5)["ev_pass"]
    worse = gate.measure(_frame(0.0), _frame(0.0, clip_rows=8), 15.0, 15.0)
    assert worse["ev_pass"] and not worse["clip_pass"] and not worse["pass"]
    blank = PIL_Image.new("RGB", (64, 64), (0, 0, 0))
    assert "refused" in gate.measure(blank, blank, 15.0, 15.0)
