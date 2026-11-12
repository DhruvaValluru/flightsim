"""Swarm lane aircraft_exterior.pbr_materials.alpine: what is checkable on the
Mac. Source-level only: the bake's determinism and tiling, the albedo contract
of the shader's Python twin, the HLSL constants, the gate's arithmetic. No
rendered frame is measured here; the pixel gate runs on the Windows laptop.
"""

from __future__ import annotations

import itertools
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm" / "lanes" / "aircraft_exterior" / "pbr_materials" / "alpine"
sys.path.insert(0, str(LANE))

import alpine_pbr_look as look  # noqa: E402
import bake_alpine_pbr as bake  # noqa: E402
import measure_gate as gate  # noqa: E402

HLSL = (LANE / "shaders" / "alpine_detail.hlsl").read_text(encoding="utf-8")
TIERS = look.tier_table()


@pytest.fixture(scope="module")
def tier0():
    return bake.bake_tier(TIERS[0])["T_AlpineDetail_256"]


@pytest.fixture(scope="module")
def tier1():
    return bake.bake_tier(TIERS[1])


def test_committed_tier0_matches_the_generator(tier0):
    manifest = json.loads((LANE / "out" / "bake_manifest.json").read_text(encoding="utf-8"))
    row = manifest["textures"]["tier0/T_AlpineDetail_256.png"]
    assert row["pixel_sha256"] == bake.pixel_sha256(tier0)
    assert row["file_sha256"] == bake.file_sha256(LANE / "out" / "tier0" / "T_AlpineDetail_256.png")
    assert manifest["seed"] == bake.SEED and manifest["visual_only"] is True


def test_bake_is_deterministic(tier0):
    assert bake.pixel_sha256(bake.bake_tier(TIERS[0])["T_AlpineDetail_256"]) == bake.pixel_sha256(tier0)


def test_detail_channels(tier0):
    d = tier0.astype(np.float64) / 255.0
    # R, B, A are rank-equalised: mean 0.5, so the breakup never shifts the mean roughness
    for ch in (0, 2, 3):
        assert abs(d[..., ch].mean() - 0.5) < 0.01
    # frost threshold: the share above 1 - c is c
    for c in (0.1, 0.35, 0.7):
        assert abs((d[..., 2] > 1.0 - c).mean() - c) < 0.02
    # grime is sparse and streaks along U: neighbours differ less along U than along V
    g = d[..., 1]
    assert 0.03 < g.mean() < 0.25
    du = np.abs(g - np.roll(g, 1, axis=1)).mean()
    dv = np.abs(g - np.roll(g, 1, axis=0)).mean()
    assert du < 0.6 * dv


def test_every_texture_tiles(tier0, tier1):
    for arr in (tier0, *tier1.values()):
        a = arr.astype(np.float64)
        for axis in (0, 1):
            seam = np.abs(np.take(a, 0, axis=axis) - np.take(a, -1, axis=axis)).mean()
            inner = np.abs(np.take(a, 1, axis=axis) - np.take(a, 0, axis=axis)).mean()
            assert seam <= 1.5 * inner + 1.0


def test_normal_map_is_shallow_and_never_tier0(tier1):
    assert not TIERS[0]["normal_map"] and TIERS[0]["texture_samples"] == 1
    n = tier1["T_AlpineNormal_512"].astype(np.float64) / 255.0 * 2.0 - 1.0
    assert n[..., 2].min() > 0.98                       # stored, gain included
    assert np.abs(np.linalg.norm(n, axis=-1) - 1.0).max() < 0.02
    assert np.abs(n[..., :2]).max() * 127 > 6           # more than a few LSB of signal
    # decoded at the largest look amount the lane sets, the tilt stays under 2 degrees
    amount = max(s["AlpineNormalAmount"] for s in look.ALPINE_SCALARS.values())
    worst = np.abs(n[..., :2]).max()
    z = look.normal_from_texel(worst * 0.5 + 0.5, worst * 0.5 + 0.5, amount)[2]
    assert z > np.cos(np.radians(4.0))
    # the physical slope (gain divided out) matches the dish geometry
    bay_cm = look.TILE_CM / look.BAYS_V
    assert worst / look.NORMAL_STORE_GAIN < 1.2 * np.pi * look.OILCAN_DEPTH_CM / bay_cm


def test_albedo_contract_no_dark_aircraft():
    """Whatever the texel and the base colour, the lane's base colour stays in
    the class range and is never under MAX_DARKENING x the clamped input."""
    assert look.MAX_DARKENING >= 0.79
    grid = (0.0, 0.25, 0.5, 0.75, 1.0)
    for cls, (lo, hi) in look.ALBEDO_RANGE.items():
        for base in (0.0, 0.02, 0.18, 0.5, 0.9, 1.0):
            for detail in itertools.product(grid, repeat=4):
                for geo in (0.0, 1.0):
                    out = look.shade(cls, (base,) * 3, detail, 0.4, 0.0, 0.8, geo)
                    c = out["base"][0]
                    clamped = min(max(base, lo), hi)
                    assert lo - 1e-12 <= c <= hi + 1e-12
                    assert c >= max(lo, clamped * look.MAX_DARKENING) - 1e-12
                    assert look.ROUGHNESS_MIN <= out["roughness"] <= 1.0
                    # GrimeAmount beyond the clamp cannot darken further
                    worse = look.shade(cls, (base,) * 3, detail, 0.4, 0.0, 0.8, geo,
                                       {"GrimeAmount": 5.0})["base"][0]
                    assert worse >= max(lo, clamped * look.MAX_DARKENING) - 1e-12


def test_frost_only_brightens_and_kills_the_coat():
    dry = look.shade("paint", (0.05, 0.05, 0.05), (0.5, 0.0, 1.0, 1.0), 0.4, 0.0, 0.8, 0.0)
    icy = look.shade("paint", (0.05, 0.05, 0.05), (0.5, 0.0, 1.0, 1.0), 0.4, 0.0, 0.8, 1.0)
    assert dry["frost"] == 0.0 and icy["frost"] > 0.5
    assert icy["base"][0] > dry["base"][0] and icy["roughness"] > dry["roughness"]
    assert icy["clear_coat"] < dry["clear_coat"]
    white = look.shade("paint", (0.9,) * 3, (0.5, 0.0, 1.0, 1.0), 0.4, 0.0, 0.8, 1.0)
    assert white["base"][0] == pytest.approx(0.9)
    metal = look.shade("bare_metal", (0.92,) * 3, (0.5, 0.0, 1.0, 1.0), 0.35, 1.0, 0.0, 1.0)
    assert metal["metallic"] < 1.0


def test_paint_range_agrees_with_the_class_masters():
    sys.path.insert(0, str(REPO / "scripts"))
    import aircraft_look
    assert look.ALBEDO_RANGE["paint"][1] == aircraft_look.CLASS_SCALARS["paint"]["AlbedoMax"]
    assert look.ALBEDO_RANGE["rubber"][0] == pytest.approx(aircraft_look.TIRE_ALBEDO[0], abs=1e-3)
    for cls, overrides in look.ALPINE_SCALARS.items():
        assert cls in aircraft_look.CLASS_SCALARS
        assert overrides["GrimeAmount"] <= look.GRIME_AMOUNT_MAX


def test_hlsl_constants_match_the_twin():
    pairs = {"ALPINE_TILE_CM": look.TILE_CM, "ALPINE_ALBEDO_MOD_MIN": look.ALBEDO_MOD_MIN,
             "ALPINE_GRIME_DARKEN_MAX": look.GRIME_DARKEN_MAX,
             "ALPINE_GRIME_AMOUNT_MAX": look.GRIME_AMOUNT_MAX,
             "ALPINE_FROST_ALBEDO": look.FROST_ALBEDO, "ALPINE_FROST_ROUGHNESS": look.FROST_ROUGHNESS,
             "ALPINE_FROST_SOFTNESS": look.FROST_SOFTNESS, "ALPINE_ROUGHNESS_MIN": look.ROUGHNESS_MIN,
             "ALPINE_GRIME_ROUGHNESS_ADD": look.GRIME_ROUGHNESS_ADD,
             "ALPINE_NORMAL_STORE_GAIN": look.NORMAL_STORE_GAIN,
             "ALPINE_TOP_PROJECTION_NZ": look.TOP_PROJECTION_NZ}
    for name, value in pairs.items():
        m = re.search(rf"#define {name} ([0-9.]+)", HLSL)
        assert m and float(m.group(1)) == pytest.approx(value), name
    # SM5-safe: no loops, no ray or Lumen calls
    assert not re.search(r"\b(for|while)\s*\(|TraceRay|Lumen", HLSL)


def test_tiers_are_estimates_and_ordered():
    est = [t["est_vram_mb"] for t in TIERS]
    assert est == sorted(est) and est[0] < 0.1 and est[-1] < 12.0
    assert all(t["sustained"] == "UNMEASURED" and "ESTIMATE" in t["est_vram_basis"] for t in TIERS)
    assert all(t["cvars"]["r.ClearCoatNormal"] == 0 for t in TIERS[:3])
    assert TIERS[0]["clear_coat"] is False


def test_provenance_has_no_fetched_or_nc_asset():
    prov = json.loads((LANE / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert prov["fetched_assets"] == [] and prov["vendored_code"] == []
    assert prov["visual_only"] is True
    for row in prov["considered_not_adopted"]:
        assert row["adopted"] is False and row["reason"]
    for row in prov["generated"]:
        assert re.fullmatch(r"[0-9a-f]{64}", row["pixel_sha256"])


def _frame(level, noise, rng, shape=(64, 64)):
    y = np.full(shape, float(level)) + rng.normal(0.0, noise, shape)
    return np.repeat(y[..., None], 3, axis=2)


def test_gate_arithmetic():
    rng = np.random.default_rng(3)
    mask = np.zeros((64, 64), dtype=bool)
    mask[8:56, 8:56] = True
    ref = _frame(140, 1.0, rng)
    ok = gate.measure(ref, _frame(138, 2.0, rng), mask)
    assert ok["pass"] and ok["detail_ratio"] > 2.0
    dark = gate.measure(ref, _frame(60, 2.0, rng), mask)
    assert not dark["pass_luminance"] and not dark["pass"]
    black = gate.measure(ref, _frame(10, 2.0, rng), mask)
    assert not black["pass_dark_share"]
    flat = gate.measure(ref, ref.copy(), mask)
    assert flat["luminance_ratio"] == pytest.approx(1.0) and not flat["pass_detail"]
    with pytest.raises(ValueError):
        gate.measure(ref, ref, np.zeros((64, 64), dtype=bool))
