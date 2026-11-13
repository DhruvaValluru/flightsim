import json

import pytest

from core.render.hardware_budget import HardwareProfileError, budget, load_profile


def _profile(vram, name="NVIDIA GeForce RTX 4070", vendor="nvidia"):
    return {
        "cpu": {"logical_cores": 16},
        "ram": {"total_gb": 32},
        "gpus": [{"vendor": vendor, "name": name, "vram_mb": vram}],
    }


def test_tiers_follow_vram():
    assert budget(_profile(4_000))["tier"] == "floor"
    assert budget(_profile(8_000))["tier"] == "mid"
    assert budget(_profile(12_000))["tier"] == "high"
    assert budget(_profile(24_000))["tier"] == "extreme"


def test_reserve_and_workers():
    b = budget(_profile(12_000))
    assert b["usable_vram_mb"] == 10_200
    assert b["cpu_workers"] == 14
    assert b["gpu_render_jobs"] == 1
    assert b["measured"] is False


def test_hardware_rt_needs_rtx_and_vram():
    assert budget(_profile(12_000))["hardware_ray_tracing"] is True
    assert budget(_profile(6_000))["hardware_ray_tracing"] is False
    assert budget(_profile(12_000, "NVIDIA GTX 1080", "nvidia"))["hardware_ray_tracing"] is False


def test_refuses_by_name(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"cpu": {}, "ram": {}, "gpus": []}), encoding="utf-8")
    with pytest.raises(HardwareProfileError, match="no_gpu"):
        load_profile(p)
    p.write_text(json.dumps({"cpu": {}, "ram": {}}), encoding="utf-8")
    with pytest.raises(HardwareProfileError, match="missing_gpus"):
        load_profile(p)


def test_intel_igpu_gets_the_conservative_budget():
    p = {"cpu": {"logical_cores": None}, "ram": {"total_gb": None},
         "gpus": [{"vendor": "intel", "name": "Intel integrated graphics", "vram_mb": None}]}
    b = budget(p)
    assert b["tier"] == "integrated" and b["rhi"] == "d3d11"
    assert b["hardware_ray_tracing"] is False and b["max_capture_width"] == 1280
    assert b["measured"] is False
    assert set(b["unknown_inputs"]) == {"cpu.logical_cores", "ram.total_gb"}


def test_igpu_streaming_pool_is_a_share_of_the_usable_vram_not_all_of_it():
    # Scene #09 (2026-11-13): the pool was the whole usable VRAM (491 = 491),
    # leaving nothing for render targets, shadows and the tile textures.
    from core.render.hardware_budget import (INTEGRATED_POOL_FLOOR_MB, INTEGRATED_POOL_SHARE,
                                             integrated_streaming_pool_mb)
    p = {"cpu": {"logical_cores": None}, "ram": {"total_gb": None},
         "gpus": [{"vendor": "intel", "name": "Intel integrated graphics", "vram_mb": None, "integrated": True}]}
    b = budget(p)
    assert b["usable_vram_mb"] == 491
    pool = b["cvars"]["r.Streaming.PoolSize"]
    assert pool == 163 and pool < b["usable_vram_mb"]
    assert INTEGRATED_POOL_SHARE == 1 / 3 and INTEGRATED_POOL_FLOOR_MB == 128
    # the floor, and never above the usable VRAM
    assert integrated_streaming_pool_mb(200) == 128
    assert integrated_streaming_pool_mb(100) == 100
    assert integrated_streaming_pool_mb(1024) == 341


def test_discrete_gpu_pool_is_unchanged():
    assert budget(_profile(12_000))["cvars"]["r.Streaming.PoolSize"] == int(10_200 * 0.6)
