"""Hardware profile -> render budget.

Reads docs/hardware/hardware_profile.json (written by scripts/hw_probe.ps1 on
the Windows machine) and turns it into STARTING budgets for the hyper-realism
work. These are starting points only: the swarm's stress-ladder lane measures
the real ceiling (frame time, VRAM, thermals) and overwrites them with
measured values. Nothing here is a claim about what the machine can sustain.
"""
from __future__ import annotations

import json
from pathlib import Path

REQUIRED = ("cpu", "ram", "gpus")
VRAM_RESERVE = 0.15  # leave headroom for the OS compositor and the editor

TIERS = ((20_000, "extreme"), (12_000, "high"), (6_000, "mid"), (0, "floor"))


class HardwareProfileError(ValueError):
    """Raised with a name, like the rest of the project's refusals."""


def load_profile(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    # One literal name per key (REQUIRED), so the refusal catalogue can see each.
    if "cpu" not in data:
        raise HardwareProfileError("hardware_profile.missing_cpu")
    if "ram" not in data:
        raise HardwareProfileError("hardware_profile.missing_ram")
    if "gpus" not in data:
        raise HardwareProfileError("hardware_profile.missing_gpus")
    if not data["gpus"]:
        raise HardwareProfileError("hardware_profile.no_gpu")
    return data


def _primary_gpu(profile: dict) -> dict:
    return max(profile["gpus"], key=lambda g: g.get("vram_mb") or 0)


def _integrated(gpu: dict) -> bool:
    if gpu.get("integrated") is not None:
        return bool(gpu["integrated"])
    name = gpu.get("name", "").upper()
    return gpu.get("vendor") == "intel" and "ARC A" not in name and "ARC B" not in name


def _integrated_budget(profile: dict, gpu: dict) -> dict:
    """Shared-memory GPU on D3D11: the measured case on the owner's laptop
    (12 device-lost crashes on scene 9). Conservative until a stress run."""
    ram_gb = profile["ram"].get("total_gb") or 8
    pool = min(1024, int(ram_gb * 1024 * 0.06))
    unknown = [k for k in ("cpu.logical_cores", "ram.total_gb")
               if (profile["cpu"].get("logical_cores") if k.startswith("cpu") else profile["ram"].get("total_gb")) is None]
    return {
        "tier": "integrated",
        "gpu": gpu.get("name"),
        "rhi": "d3d11",
        "usable_vram_mb": pool,
        "hardware_ray_tracing": False,
        "max_capture_width": 1280,
        "cpu_workers": max(1, (profile["cpu"].get("logical_cores") or 4) - 2),
        "gpu_render_jobs": 1,
        "ram_cache_gb": 1,
        "cvars": {
            "r.Streaming.PoolSize": pool,
            "r.ScreenPercentage": 100,
            "sg.TextureQuality": 1, "sg.ShadowQuality": 1,
            "sg.GlobalIlluminationQuality": 1, "sg.PostProcessQuality": 2,
            "r.DynamicGlobalIlluminationMethod": 0,
        },
        "unknown_inputs": unknown,
        "measured": False,
    }


def _hardware_rt(gpu: dict) -> bool:
    name = gpu.get("name", "").upper()
    if gpu.get("vendor") == "nvidia":
        return "RTX" in name
    if gpu.get("vendor") == "amd":
        return any(f"RX {n}" in name for n in ("6", "7", "9"))
    return False


def budget(profile: dict) -> dict:
    gpu = _primary_gpu(profile)
    if _integrated(gpu):
        return _integrated_budget(profile, gpu)
    vram = int(gpu.get("vram_mb") or 0)
    if vram <= 0:
        raise HardwareProfileError("hardware_profile.vram_unknown")
    tier = next(name for floor, name in TIERS if vram >= floor)
    usable_vram = int(vram * (1 - VRAM_RESERVE))
    logical = int(profile["cpu"].get("logical_cores", 4))
    ram_gb = int(profile["ram"].get("total_gb", 8))
    rt = _hardware_rt(gpu) and vram >= 8_000
    cvars = {
        "r.Streaming.PoolSize": int(usable_vram * 0.6),
        "r.Lumen.HardwareRayTracing": int(rt),
        "r.ScreenPercentage": {"floor": 100, "mid": 100, "high": 150, "extreme": 200}[tier],
        "sg.TextureQuality": 3 if tier != "floor" else 1,
        "sg.ShadowQuality": 3 if tier in ("high", "extreme") else 2,
        "sg.GlobalIlluminationQuality": 3 if tier in ("high", "extreme") else 2,
        "sg.PostProcessQuality": 3,
        "r.Nanite.MaxPixelsPerEdge": 1 if tier == "extreme" else 2,
    }
    return {
        "tier": tier,
        "gpu": gpu.get("name"),
        "usable_vram_mb": usable_vram,
        "hardware_ray_tracing": rt,
        "max_capture_width": {"floor": 1920, "mid": 2560, "high": 3840, "extreme": 7680}[tier],
        "cpu_workers": max(1, logical - 2),
        "gpu_render_jobs": 1,  # one commandlet owns the GPU; more only thrash VRAM
        "ram_cache_gb": max(1, int(ram_gb * 0.25)),
        "cvars": cvars,
        "measured": False,  # flipped by the stress-ladder lane, never by this module
    }


def budget_from_file(path: str | Path = "docs/hardware/hardware_profile.json") -> dict:
    return budget(load_profile(path))
