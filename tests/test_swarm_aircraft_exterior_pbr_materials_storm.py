"""Lane aircraft_exterior.pbr_materials.storm: what the Mac can check.

Source-level only: the bake's bytes, the BC5 codec, the albedo budget and the
numbers the lane copies from shared code. No frame is rendered here, so
nothing below is a visual result (CLAUDE.md: those come from the Windows
laptop, INTEGRATION.md has the command).
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm" / "lanes" / "aircraft_exterior" / "pbr_materials" / "storm"
sys.path.insert(0, str(LANE))
sys.path.insert(0, str(REPO / "scripts"))

import bake_storm_pbr as bake  # noqa: E402
import measure_aircraft_gate as gate  # noqa: E402


def test_shared_numbers_are_the_shared_codes_numbers():
    from core.scene import beauty_look, weather_look
    import aircraft_look
    import aircraft_wet_layer as wet

    s = bake.SHARED
    assert s["rain_rate_mmh"] == weather_look.STORM_RAIN_MMH
    assert s["wet_saturation_mmh"] == wet.WET_DEFAULTS["WetSaturationMmh"]
    assert s["airframe_wetness"] == min(1.0, s["rain_rate_mmh"] / s["wet_saturation_mmh"])
    assert s["exposure_meter_target_p90"] == beauty_look.EXPOSURE_METER_TARGET_P90["storm"]
    grade = beauty_look.GRADES["storm"]
    assert s["colour_temperature_k"] == grade["WhiteTemp"]
    assert s["grade_saturation"] == grade["ColorSaturation"][3]
    assert s["grade_contrast"] == grade["ColorContrast"][3]
    assert s["ev100_offset"] == grade["ev100_offset"]
    paint = aircraft_look.CLASS_SCALARS["paint"]
    assert bake.HEAD == {"PorosityPaint": wet.WET_DEFAULTS["PorosityPaint"],
                         "PorosityBareMetal": wet.WET_DEFAULTS["PorosityBareMetal"],
                         "GrimeAmount": paint["GrimeAmount"], "PanelDarkening": paint["PanelDarkening"],
                         "AlbedoMax": paint["AlbedoMax"]}


def test_overrides_only_name_parameters_that_exist_or_are_declared_new():
    import aircraft_look
    import aircraft_wet_layer as wet

    assert set(bake.STORM_OVERRIDES["wet"]) <= set(wet.WET_DEFAULTS)
    assert set(bake.STORM_OVERRIDES["paint"]) - set(aircraft_look.CLASS_SCALARS["paint"]) == {"AlbedoMin"}
    assert set(bake.STORM_OVERRIDES["bare_metal"]) <= set(aircraft_look.CLASS_SCALARS["bare_metal"])
    # the film is never rougher than HEAD's, and the storm never raises a darkening knob
    assert bake.STORM_OVERRIDES["wet"]["WetRoughness"] <= wet.WET_DEFAULTS["WetRoughness"]
    for key in ("PorosityPaint", "PorosityBareMetal"):
        assert bake.STORM_OVERRIDES["wet"][key] <= bake.HEAD[key]
    for key in ("GrimeAmount", "PanelDarkening"):
        assert bake.STORM_OVERRIDES["paint"][key] <= bake.HEAD[key]


def test_albedo_stays_in_the_calibrated_range_and_never_darker_than_head():
    lo, hi = (bake.srgb_to_linear(v) for v in bake.ALBEDO_SRGB_RANGE)
    paint = bake.STORM_OVERRIDES["paint"]
    assert paint["AlbedoMin"] == pytest.approx(lo, abs=1e-4)
    assert paint["AlbedoMax"] == pytest.approx(hi, abs=5e-3)
    _, means = bake.bake_maps(0)                 # the area means are the baked masks' own
    budget = bake.albedo_budget(means["grime"], means["groove"])
    assert budget["pass"]
    assert budget["worst_ratio"] >= bake.BUDGET["worst_min"]
    assert budget["mean_ratio"] >= bake.BUDGET["mean_min"]
    assert budget["vs_head_worst"] >= 1.0 and budget["vs_head_mean"] >= 1.0
    # HEAD's own worst case is what the lane exists to fix: it fails this budget
    assert budget["head_worst_ratio"] < bake.BUDGET["worst_min"]
    # a pure black or pure white livery is clamped into the range before the film
    out = bake.effective_albedo([0.0, 1.0], 0.0, 0.0, 0.0, albedo_min=lo, albedo_max=hi)
    assert out[0] == pytest.approx(lo) and out[1] == pytest.approx(hi)


def test_wet_film_never_brightens():
    a = np.linspace(0.03, 0.9, 20)
    wet = bake.effective_albedo(a, 0.05, 0.0, 0.0, wetness=1.0)
    assert np.all(wet <= a + 1e-12)


def test_bc4_round_trip_is_within_the_formats_error():
    rng = np.random.default_rng(3)
    smooth = bake.to_u8(bake._fft_noise(rng, 64, 6.0, 6.0))
    back = bake.bc4_decode(bake._bc4_blocks(smooth), 64, 64)
    assert np.abs(back.astype(int) - smooth.astype(int)).max() <= 6
    flat = np.full((8, 8), 255, np.uint8)
    assert np.array_equal(bake.bc4_decode(bake._bc4_blocks(flat), 8, 8), flat)
    flat0 = np.zeros((8, 8), np.uint8)
    assert np.array_equal(bake.bc4_decode(bake._bc4_blocks(flat0), 8, 8), flat0)


def test_dds_header_and_mip_chain_bytes():
    rg = np.random.default_rng(1).random((64, 64, 2))
    data = bake.dds_bc5(rg)
    assert data[:4] == b"DDS " and data[84:88] == b"ATI2"
    size, flags, height, width, linear, depth, mips = struct.unpack_from("<7I", data, 4)
    assert (size, height, width, mips) == (124, 64, 64, 7)
    assert linear == 16 * 16 * 16
    blocks = sum(max(1, (64 >> m) // 4) ** 2 for m in range(7))
    assert len(data) == 128 + 16 * blocks


def test_maps_tile_and_the_normal_is_flat_on_average():
    maps, means = bake.bake_maps(0)
    assert set(maps) == {"PanelN", "Wet"}
    for rg in maps.values():
        assert rg.shape == (256, 256, 2) and rg.min() >= 0.0 and rg.max() <= 1.0
    # tiling: the wrap seam is no rougher than the roughest interior step. The
    # panel map is checked on its HEIGHT: its slope legitimately flips sign
    # across the seam, which is the bottom of the groove.
    height, _ = bake.panel_fields(256, 0, np.random.Generator(np.random.PCG64(bake.SEED)))
    for name, field in (("Wet", maps["Wet"]), ("height", height)):
        for axis in (0, 1):
            step = np.abs(np.diff(field, axis=axis)).max()
            seam = np.abs(np.take(field, 0, axis=axis) - np.take(field, -1, axis=axis)).max()
            assert seam <= step + 1e-9, (name, axis)
    assert np.abs(maps["PanelN"].mean(axis=(0, 1)) - 0.5).max() < 0.01
    assert 0.4 < means["grime"] < 0.6
    assert 0.05 < means["rivulet"] < 0.5


def test_bake_is_deterministic_and_matches_the_committed_tier0(tmp_path):
    first = bake.bake(0, tmp_path / "a")
    second = bake.bake(0, tmp_path / "b")
    assert first["files"] == second["files"]
    assert first["albedo_budget"]["pass"]
    committed = json.loads((LANE / "baked" / "tier0" / "storm_look.json").read_text())
    assert committed["files"] == first["files"]
    provenance = json.loads((LANE / "PROVENANCE.json").read_text())
    for name, row in first["files"].items():
        assert provenance["generated"]["tier0"][name] == row["sha256"]


def test_tiers_are_estimates_and_tier0_fits_the_laptop():
    assert bake.vram_mb(0) < 1.0
    assert [bake.vram_mb(t) for t in sorted(bake.TIERS)] == sorted(bake.vram_mb(t) for t in bake.TIERS)
    assert bake.vram_mb(3) < 491 * 0.05      # even the top tier is under 5 % of the pool (ESTIMATE)
    maps, _ = bake.bake_maps(1)
    assert set(maps) == {"PanelN", "Wet", "Aux"}


def test_provenance_vendors_nothing_and_names_only_commercial_licences():
    provenance = json.loads((LANE / "PROVENANCE.json").read_text())
    assert provenance["vendored"] == []
    for row in provenance["considered_not_vendored"]:
        assert row["decision"].startswith("not vendored")
    text = json.dumps(provenance["used"]).lower()
    assert "non-commercial" not in text and "by-nc" not in text


def _frame(body, highlight, shape=(60, 80)):
    rgb = np.full(shape + (3,), 120, np.uint8)
    mask = np.zeros(shape, np.uint8)
    mask[10:50, 10:70] = 7
    rgb[10:50, 10:70] = body
    rgb[10:14, 10:70] = highlight
    return rgb, mask


def test_gate_fails_a_darker_aircraft_and_passes_a_wetter_one():
    base = _frame(60, 90)
    wetter = _frame(60, 140)
    darker = _frame(45, 140)
    assert gate.gate(*base, *wetter)["pass"]
    result = gate.gate(*base, *darker)
    assert not result["pass"] and not result["checks"]["dark_ratio"]
    same = gate.gate(*base, *base)
    assert not same["pass"] and same["checks"]["dark_ratio"] and not same["checks"]["sheen_gain"]
    blown = gate.gate(*base, *_frame(60, 255))
    assert not blown["checks"]["clip_share"]


def test_gate_refuses_a_frame_with_no_aircraft():
    rgb, mask = _frame(60, 90)
    with pytest.raises(ValueError, match="storm_pbr.gate"):
        gate.gate(rgb, np.zeros_like(mask), rgb, mask)
