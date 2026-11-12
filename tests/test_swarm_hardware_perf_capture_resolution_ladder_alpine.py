"""Source-level checks for the alpine capture-resolution ladder lane (Mac).

These check the plan's projection arithmetic, the committed files against the
generator, the resolver on a SYNTHETIC analytic scene and the gate's parsers
and decision table. They are NOT a render or pixel result: frame time, VRAM,
temperature and the real frame are measured on the Windows laptop (the
lane's INTEGRATION.md).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm" / "lanes" / "hardware_perf" / "capture_resolution_ladder" / "alpine"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"alpine_capladder_{name}", LANE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bake = _load("bake_capture_ladder")
res = _load("resolve_capture")
gate = _load("measure_capture_gate")
PLAN = json.loads((LANE / "alpine_capture_ladder.json").read_text())
NOISE = res.load_noise()


def synthetic_pass(tier, p):
    """Point-sample an analytic ridge-against-sky scene through one pass window."""
    w, h = tier["delivered_px"]
    rw, rh = tier["pass_render_px"]
    x0, y0 = p["window_px"][:2]
    x = ((x0 + np.arange(rw) + 0.5) / w)[None, :]
    y = ((y0 + np.arange(rh) + 0.5) / h)[:, None]
    ridge = 0.45 + 0.10 * np.abs(((x * 3.0) % 1.0) - 0.5) + 0.03 * np.sin(x * 40.0)
    sky = 0.20 + 0.05 * y + 0 * x
    snow = 0.75 + 0.10 * np.sin(x * 900.0) * np.sin(y * 700.0)
    # rock detail with a 3 px period at 2560 wide: below Nyquist at 1280, resolved at 2560
    snow = snow + np.where(y > 0.6, 0.08 * np.sin(x * 2 * np.pi * 2560 / 3.0) * np.sin(y * 2 * np.pi * 1600 / 3.0), 0.0)
    lin = np.where(y < ridge, sky, snow)
    u8 = np.round(res.linear_to_srgb(lin) * 255).astype(np.uint8)
    return np.repeat(u8[..., None], 3, axis=2)


@pytest.fixture(scope="module")
def frames():
    return {t["tier"]: res.resolve(t, lambda p, t=t: synthetic_pass(t, p), NOISE) for t in PLAN["tiers"]}


def test_committed_files_are_what_the_generator_writes(tmp_path):
    bake.write(tmp_path)
    for name in ("alpine_capture_ladder.json", "blue_noise_64.r8"):
        assert (tmp_path / name).read_bytes() == (LANE / name).read_bytes(), name


def test_provenance_hashes_and_labels():
    prov = json.loads((LANE / "PROVENANCE.json").read_text())
    assert prov["label"] == "visual-only" and prov["vendored"] == [] and prov["fetched_assets"] == []
    for entry in prov["generated"]:
        assert hashlib.sha256((LANE / entry["file"]).read_bytes()).hexdigest() == entry["sha256"], entry["file"]
    for source in prov["sources"]:
        assert source["name"] and source["licence"]
        assert "non-commercial" not in source["licence"].lower()


def test_plan_is_unmeasured_and_stays_inside_the_start_budget():
    assert PLAN["measured"] is False
    assert [t["tier"] for t in PLAN["tiers"]] == [0, 1, 2, 3]
    t0 = PLAN["tiers"][0]
    assert t0["delivered_px"] == [1280, 800] and t0["pass_count"] == 1
    for t in PLAN["tiers"]:
        rw, rh = t["pass_render_px"]
        # no single GPU frame is more than 14 % above the 1280x800 start
        assert rw * rh <= 1.14 * 1280 * 800
        assert t["delivered_px"][0] * 10 == t["delivered_px"][1] * 16      # 16:10 like the panel
        assert abs(sum(p["weight"] for p in t["passes"]) - t["grid"][0] * t["grid"][1]) < 1e-12
        assert t["est_render_target_mb"] < PLAN["target"]["start_usable_vram_mb"] / 4


def test_ndc_window_maps_the_pass_window_to_clip_space():
    for t in PLAN["tiers"]:
        w, h = t["delivered_px"]
        for p in t["passes"]:
            x0, y0, x1, y1 = p["window_px"]
            (sx, sy), (ox, oy) = p["ndc_scale"], p["ndc_offset"]
            assert [x1 - x0, y1 - y0] == t["pass_render_px"]
            for px, want in ((x0, -1.0), (x1, 1.0)):
                assert sx * (2 * px / w - 1) + ox == pytest.approx(want, abs=1e-12)
            for py, want in ((y0, 1.0), (y1, -1.0)):
                assert sy * (1 - 2 * py / h) + oy == pytest.approx(want, abs=1e-12)
    first = PLAN["tiers"][0]["passes"][0]
    assert first["ndc_scale"] == [1.0, 1.0] and first["ndc_offset"] == [0.0, 0.0]


def test_jitter_is_a_rotated_grid():
    xs = sorted(j[0] for j in bake.RGSS4)
    ys = sorted(j[1] for j in bake.RGSS4)
    assert xs == ys == [-0.375, -0.125, 0.125, 0.375]
    assert sum(xs) == 0


def test_blue_noise_is_uniform_and_has_no_low_frequencies():
    n = NOISE.astype(np.float64)
    assert NOISE.shape == (64, 64)
    assert set(np.bincount(NOISE.ravel(), minlength=256)) == {16}
    power = np.abs(np.fft.fft2(n - n.mean())) ** 2
    f = np.fft.fftfreq(64)
    r = np.hypot(*np.meshgrid(f, f))
    assert power[(r > 0) & (r < 1 / 16)].mean() < 0.01 * power[r > 0].mean()


def test_tiles_stitch_to_exactly_the_single_pass_frame(frames):
    t2 = PLAN["tiers"][2]
    whole = {"tier": 9, "delivered_px": t2["delivered_px"], "pass_render_px": t2["delivered_px"],
             "payload_px": t2["delivered_px"], "gutter_px": 0,
             "passes": [{"paste_px": [0, 0], "window_px": [0, 0, *t2["delivered_px"]], "weight": 1.0}]}
    direct = res.resolve(whole, lambda p: synthetic_pass(whole, p), NOISE)
    assert np.array_equal(frames[2], direct)
    assert gate.seam_excess(frames[2][..., 0], t2["grid"]) <= PLAN["gate"]["seam_excess_levels_ceiling"]


def test_seam_metric_catches_a_tile_with_different_exposure(frames):
    bad = frames[2].astype(np.float64)
    bad[:800, :1280] *= 1.03                      # one tile 3 % brighter
    assert gate.seam_excess(bad[..., 0], [2, 2]) > PLAN["gate"]["seam_excess_levels_ceiling"]
    assert gate.seam_excess(frames[0][..., 0], [1, 1]) == 0.0


def test_pixel_gate_passes_the_heavier_tiers_on_the_synthetic_scene(frames):
    from PIL import Image
    g = PLAN["gate"]
    ref = Image.fromarray(frames[0])
    same = gate.pixel_metrics(ref, ref, (83, 317, 1167, 467), (100, 500, 1100, 780))
    assert same == {"alias_ratio": 1.0, "ground_sharpness_ratio": 1.0}
    for tier in (1, 2, 3):
        m = gate.pixel_metrics(ref, Image.fromarray(frames[tier]), (83, 317, 1167, 467), (100, 500, 1100, 780))
        assert m["alias_ratio"] <= g["alias_ratio_ceiling"], (tier, m)
        if str(tier) in g["ground_sharpness_floor"]:
            assert m["ground_sharpness_ratio"] >= g["ground_sharpness_floor"][str(tier)], (tier, m)
        print(tier, m)


def test_sample_spread_separates_sub_pixel_jitter_from_a_moved_camera():
    t1 = PLAN["tiers"][1]
    still = res.sample_spread(t1, lambda p: synthetic_pass(t1, p))
    assert still <= PLAN["gate"]["sample_spread_levels_ceiling"]

    def drifting(p):                              # exposure creeps 2 % per pass
        return np.clip(synthetic_pass(t1, p) * (1 + 0.02 * p["sample"]), 0, 255).astype(np.uint8)

    assert res.sample_spread(t1, drifting) > PLAN["gate"]["sample_spread_levels_ceiling"]
    assert res.sample_spread(PLAN["tiers"][0], lambda p: synthetic_pass(PLAN["tiers"][0], p)) == 0.0


def test_dither_keeps_a_gradient_finer_than_one_level():
    truth = np.linspace(100.2, 102.8, 1280)[None, :, None].repeat(128, 0).repeat(3, 2) / 255.0
    dithered = res.dither_to_u8(truth, NOISE)[..., 0].astype(np.float64)
    rounded = np.round(truth[..., 0] * 255)
    blocks = lambda a: a.reshape(2, 64, 20, 64).mean(axis=(1, 3))      # 64x64 means
    assert np.abs(blocks(dithered) - blocks(truth[..., 0] * 255)).max() < 0.02
    assert np.abs(blocks(rounded) - blocks(truth[..., 0] * 255)).max() > 0.2


def test_step_down_pass_is_resized_to_the_planned_size():
    t0 = PLAN["tiers"][0]
    small = np.full((640, 1024, 3), 128, np.uint8)
    out = res.resolve(t0, lambda p: small, NOISE)
    assert out.shape == (800, 1280, 3) and abs(out.mean() - 128) < 0.6
    assert PLAN["tier0_step_down"][0]["pass_render_px"] == [1024, 640]


def test_sharpness_and_alias_metrics_move_the_right_way():
    rng = np.random.default_rng(1)
    noise = rng.random((64, 64)) * 255
    smooth = (noise[:-1, :-1] + noise[1:, :-1] + noise[:-1, 1:] + noise[1:, 1:]) / 4
    assert gate.sharpness(smooth) < gate.sharpness(noise)
    checker = np.indices((32, 32)).sum(0) % 2 * 255.0
    ramp = np.tile(np.arange(32.0), (32, 1))
    assert gate.alias_fraction(checker) > 0.99 and gate.alias_fraction(ramp) < 1e-9


def test_typeperf_frames_and_log_parsers():
    head = ('"(PDH-CSV 4.0)","\\\\PC\\GPU Adapter Memory(luid_0)\\Shared Usage",'
            '"\\\\PC\\GPU Adapter Memory(luid_0)\\Dedicated Usage",'
            '"\\\\PC\\Thermal Zone Information(\\_TZ.TZ00)\\Temperature",'
            '"\\\\PC\\Thermal Zone Information(\\_TZ.TZ00)\\High Precision Temperature"')
    text = head + '\n"t0","104857600","0","340","3432"\n"t1"," ","0","341","3440"\n'
    parsed = gate.parse_typeperf(text)
    assert parsed["gpu_bytes"] == [104857600.0]
    assert parsed["temp_c"] == pytest.approx([70.05, 70.85])
    frames_csv = "EVENTS,FrameTime,GPUTime\n,16.5,9\n,812.0,700\n[Platform],1\n"
    assert gate.parse_frames(frames_csv) == [16.5, 812.0]
    assert gate.parse_frames("") == []
    log = "LogD3D11RHI: Error: DXGI_ERROR_DEVICE_HUNG\nLogTemp: fine\nLogRHI: GPU crash detected\n"
    assert gate.count_device_lost(log) == 2


def test_decision_table_and_measured_patch():
    g = PLAN["gate"]
    t2 = PLAN["tiers"][2]
    good = {"device_lost_lines": 0, "max_frame_ms": 640.0, "gpu_mb_above_idle": 410.0, "peak_temp_c": 78.0,
            "seam_excess_levels": 0.2, "alias_ratio": 0.5, "ground_sharpness_ratio": 1.3}
    verdict = gate.decide(t2, g, good)
    assert verdict["passed"]
    patch = gate.measured_patch(t2, verdict)
    assert patch["measured"] is True and patch["max_capture_width"] == 2560
    assert patch["max_pass_render_px"] == [1344, 864]
    for key, bad in (("device_lost_lines", 1), ("max_frame_ms", 1200.0), ("gpu_mb_above_idle", 600.0),
                     ("peak_temp_c", 96.0), ("seam_excess_levels", 3.0), ("alias_ratio", 0.9),
                     ("ground_sharpness_ratio", 0.8)):
        v = gate.decide(t2, g, {**good, key: bad})
        assert v["failed"] == [key] and gate.measured_patch(t2, v) is None
    # a missing measurement is not a pass and never sets measured=true
    no_temp = gate.decide(t2, g, {k: v for k, v in good.items() if k != "peak_temp_c"})
    assert no_temp["unmeasured"] == ["peak_temp_c"] and not no_temp["passed"]
    assert gate.measured_patch(t2, no_temp) is None
    # tier 0 is the reference: stability checks only
    assert set(gate.decide(PLAN["tiers"][0], g, good)["checks"]) == {
        "device_lost_lines", "max_frame_ms", "gpu_mb_above_idle", "peak_temp_c"}
    # multi-sample tiers also need the resolver's sample spread; tier 1 has no sharpness floor
    t1 = gate.decide(PLAN["tiers"][1], g, good)
    assert t1["unmeasured"] == ["sample_spread_levels"] and "ground_sharpness_ratio" not in t1["checks"]
    assert gate.decide(PLAN["tiers"][3], g, {**good, "sample_spread_levels": 0.3})["passed"]
