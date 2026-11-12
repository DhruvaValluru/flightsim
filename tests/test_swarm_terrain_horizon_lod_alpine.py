"""Source-level checks for the alpine horizon / tile level-of-detail lane (Mac).

These check the plan's geometry against closed forms, the committed files
against the generator, and the pixel gate's arithmetic on SYNTHETIC images.
They are NOT a render or pixel result: ground sample distance and horizon
range are measured on the Windows laptop (the lane's INTEGRATION.md).
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
LANE = REPO / "swarm" / "lanes" / "terrain" / "horizon_lod" / "alpine"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"alpine_hlod_{name}", LANE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bake = _load("bake_alpine_horizon_lod")


@pytest.fixture(scope="module")
def plan():
    return bake.build()


def test_committed_plan_is_what_the_generator_writes(plan, tmp_path):
    bake.write(tmp_path)
    for name in ("alpine_horizon_lod.json", "alpine_horizon_lod_curve.csv"):
        assert (tmp_path / name).read_bytes() == (LANE / name).read_bytes(), name


def test_provenance_hashes_and_labels():
    prov = json.loads((LANE / "PROVENANCE.json").read_text())
    assert prov["label"] == "visual-only"
    assert prov["vendored"] == []
    for entry in prov["generated"]:
        digest = hashlib.sha256((LANE / entry["file"]).read_bytes()).hexdigest()
        assert digest == entry["sha256"], entry["file"]
    for source in prov["sources"]:
        assert source["name"] and source["licence"]
        assert "non-commercial" not in source["licence"].lower()


def test_horizon_closed_form(plan):
    h = 4500.0
    d = bake.horizon_distance_m(h)
    # Pythagoras on the tangent triangle
    assert d ** 2 + bake.EARTH_RADIUS_M ** 2 == pytest.approx((bake.EARTH_RADIUS_M + h) ** 2, rel=1e-12)
    assert plan["horizon"]["range_km"] == pytest.approx(239.5, abs=0.1)
    assert math.tan(math.radians(bake.horizon_dip_deg(h))) == pytest.approx(d / bake.EARTH_RADIUS_M, rel=1e-9)
    # the gate uses the unrefracted horizon; the real one is farther
    assert plan["horizon"]["real_world_refracted_range_km"] > plan["horizon"]["range_km"]


@pytest.mark.parametrize("km", [5, 30, 80, 150])
def test_range_inversion_round_trip(km):
    dep = bake.depression_deg(km * 1000.0, 4500.0)
    assert bake.range_from_depression_m(dep, 4500.0) == pytest.approx(km * 1000.0, rel=1e-6)


def test_range_saturates_at_the_horizon():
    arc = bake.EARTH_RADIUS_M * math.acos(bake.EARTH_RADIUS_M / (bake.EARTH_RADIUS_M + 4500.0))
    assert bake.range_from_depression_m(0.0, 4500.0) == pytest.approx(arc)
    assert bake.range_from_depression_m(-3.0, 4500.0) == pytest.approx(arc)


def test_tier_ladder(plan):
    tiers = plan["tiers"]
    assert [t["tier"] for t in tiers] == [0, 1, 2, 3]
    sse = [t["maximum_screen_space_error"] for t in tiers]
    assert sse == sorted(sse, reverse=True) and len(set(sse)) == 4
    # tier 0 keeps today's selection: it must not refine past the reference
    assert sse[0] == plan["reference"]["maximum_screen_space_error"]
    assert tiers[0]["est_cost_vs_reference"] == pytest.approx(1.0)
    vram = [t["est_vram_mb"] for t in tiers]
    assert vram == sorted(vram)
    for t in tiers:
        # cost goes as 1 / SSE^2
        assert t["est_cost_vs_reference"] == pytest.approx((6.0 / t["maximum_screen_space_error"]) ** 2, rel=2e-3)
        assert "UNMEASURED" in t["status"]
        assert 1.0 <= t["maximum_screen_space_error"] <= 64.0  # the bridge's clamp
    assert plan["fallback"]["maximum_screen_space_error"] > sse[0]
    assert plan["calibration"]["status"] == "UNCALIBRATED"
    assert "Google Photorealistic 3D Tiles" in plan["ground"]


def test_tile_count_grows_with_the_log_of_range():
    args = dict(sse=6.0, height_agl_m=2000.0, near_range_m=5000.0, hfov_deg=54.4, width_px=1280, span=16.0)
    n100 = bake.tile_count(far_range_m=100e3, **args)
    n240 = bake.tile_count(far_range_m=240e3, **args)
    assert 1.0 < n240 / n100 < 1.35  # 2.4x the range, under 35 % more tiles


def test_gsd_curve_is_linear_in_distance_and_sse(plan):
    for row in plan["gsd_curve"]:
        assert row["geometric_error_bound_m_tier0"] == pytest.approx(6.0 * row["pixel_footprint_m"], rel=1e-3)
        assert row["geometric_error_bound_m_tier3"] == pytest.approx(3.0 * row["pixel_footprint_m"], rel=1e-3)


def test_no_tier_is_claimed_sustained():
    text = "".join((LANE / n).read_text() for n in ("alpine_horizon_lod.json", "INTEGRATION.md", "PROVENANCE.json"))
    assert "UNMEASURED" in text
    for claim in ("is sustained", "was sustained", "renders stably", "measured on windows:"):
        assert claim not in text.lower()


# --- the pixel gate's arithmetic, on synthetic images ----------------------

np = pytest.importorskip("numpy")
W, H, HFOV, PITCH, AGL = 640, 360, 54.4, -5.0, 4500.0


def _frame(range_km: float, texel_px: int, seed: int = 3):
    """Sky gradient over noise-textured ground whose edge is the surface point at range_km."""
    gate = _load("measure_horizon_lod")
    rng = np.random.default_rng(seed)
    dep = bake.depression_deg(range_km * 1000.0, AGL)
    f = (W / 2.0) / math.tan(math.radians(HFOV) / 2.0)
    row = int(round((H - 1) / 2.0 + f * math.tan(math.radians(dep + PITCH))))
    img = np.repeat(np.linspace(0.55, 0.75, H)[:, None], W, axis=1)
    coarse = rng.random((H // texel_px + 2, W // texel_px + 2))
    ground = np.kron(coarse, np.ones((texel_px, texel_px)))[:H, :W] * 0.5
    img[row:, :] = ground[row:, :]
    return gate, np.repeat(img[..., None], 3, axis=2), row


def test_gate_recovers_a_truncated_terrain_range():
    gate, img, row = _frame(40.0, 2)
    m = gate.measure(img, hfov_deg=HFOV, pitch_deg=PITCH, height_above_ground_m=AGL,
                     gsd_box=(100, 250, 356, 350), gsd_distance_m=8000.0, columns=(40, 600))
    assert abs(m["skyline_row_median"] - row) <= 2.0
    assert 30.0 < m["horizon_range_km"] < 55.0
    assert not m["horizon_range_saturated"]


def test_gate_effective_px_tracks_the_texel_size():
    sizes = {}
    for texel in (1, 2, 4):
        gate, img, _ = _frame(60.0, texel)
        sizes[texel] = gate.measure(img, hfov_deg=HFOV, pitch_deg=PITCH, height_above_ground_m=AGL,
                                    gsd_box=(100, 220, 356, 348), gsd_distance_m=8000.0)["effective_px"]
    assert sizes[1] < sizes[2] < sizes[4]
    assert sizes[4] / sizes[2] == pytest.approx(2.0, rel=0.35)


def test_gate_verdict(plan):
    gate, coarse, _ = _frame(60.0, 4)
    _, fine, _ = _frame(60.0, 2)
    kw = dict(hfov_deg=HFOV, pitch_deg=PITCH, height_above_ground_m=AGL,
              gsd_box=(100, 220, 356, 348), gsd_distance_m=8000.0)
    base, cand = gate.measure(coarse, **kw), gate.measure(fine, **kw)
    better = gate.verdict(base, cand, 2, plan)
    assert better["gsd_pass"] and better["gsd_ratio"] < 0.8
    same = gate.verdict(base, base, 0, plan)
    assert same["gsd_pass"] and same["gsd_ratio"] == pytest.approx(1.0)
    worse = gate.verdict(cand, base, 1, plan)
    assert not worse["pass"]
    # a 60 km skyline is short of the 100 km floor: the horizon half fails
    assert not same["horizon_pass"]


def test_gate_refuses_a_flat_box():
    gate = _load("measure_horizon_lod")
    with pytest.raises(ValueError):
        gate.effective_px(np.full((32, 32), 0.5))
