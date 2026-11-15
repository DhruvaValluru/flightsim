"""Offline generator (Mac): the alpine stress ladder for the Intel iGPU laptop.

Writes ``alpine_ladder.json``: four tiers of D3D11 / Shader Model 5 settings
for scenario 11 (the Matterhorn frame), each with the launch arguments the
renderer appends and a VRAM ESTIMATE. Nothing here is measured: a tier counts
as sustained only after ``run_ladder.py`` has run on the Windows laptop.

    python swarm/lanes/hardware_perf/stress_ladder/alpine/build_ladder.py

Stdlib only. Deterministic: the same source gives the same bytes.
"""

from __future__ import annotations

import json
from pathlib import Path

LANE = Path(__file__).resolve().parent
OUT = LANE / "alpine_ladder.json"
MIB = 1024 * 1024

#: core/render/hardware_budget.py _integrated_budget, the unmeasured start.
START_USABLE_VRAM_MB = 491
START_MAX_CAPTURE_WIDTH = 1280
DISPLAY = (1536, 960)

#: ESTIMATE inputs, bytes per shaded pixel. Deferred D3D11 path: GBuffer A-E
#: (5 x RGBA8), depth-stencil, two FP16 scene colours and the post chain.
BYTES_PER_PIXEL_BASE = 52
BYTES_PER_PIXEL_TAA = 16      # FP16 history + velocity
BYTES_PER_PIXEL_SSAO = 4
BYTES_PER_PIXEL_SSR = 8
BYTES_PER_PIXEL_CLOUD = 5     # quarter-res FP16 trace + reconstruction
SHADOW_BYTES_PER_TEXEL = 4
FIXED_MB = 120                # shaders, meshes, sky LUTs, the aircraft
CLOUD_NOISE_MB = 20
BAKED_LUT_MB = 8              # the scenario's Mac-baked tables (allowance)

#: The ladder. Alpine drives it through view distance (thin clear air, so the
#: tile cache is the big term) and snow (bright, so no GI or AO is needed to
#: read the frame at tier 0). Lumen, Nanite, virtual shadow maps and hardware
#: ray tracing are off on every tier: the laptop is D3D11 only.
TIERS = (
    {"tier": 0, "width": 960, "height": 600, "pool_mb": 192, "tile_cache_mb": 96,
     "tile_sse": 32, "shadow_res": 1024, "cascades": 2, "aa": 1, "ssao": 0,
     "ssr": 0, "clouds": 0, "aniso": 4,
     "summary": "960x600, FXAA, 2x1024 cascades, no SSAO/SSR/volumetric clouds, "
                "192 MB texture pool, 96 MB tile cache at screen-space error 32; "
                "sky, aerial perspective and AO come from the Mac-baked tables"},
    {"tier": 1, "width": 1280, "height": 800, "pool_mb": 320, "tile_cache_mb": 160,
     "tile_sse": 24, "shadow_res": 2048, "cascades": 3, "aa": 2, "ssao": 1,
     "ssr": 0, "clouds": 0, "aniso": 8,
     "summary": "1280x800, TAA, 3x2048 cascades, SSAO, 320 MB pool, 160 MB tile "
                "cache at screen-space error 24"},
    {"tier": 2, "width": 1280, "height": 800, "pool_mb": 491, "tile_cache_mb": 256,
     "tile_sse": 16, "shadow_res": 2048, "cascades": 3, "aa": 2, "ssao": 1,
     "ssr": 1, "clouds": 1, "aniso": 8,
     "summary": "tier 1 plus SSR and quarter-res volumetric clouds, 491 MB pool, "
                "256 MB tile cache at screen-space error 16"},
    {"tier": 3, "width": 1536, "height": 960, "pool_mb": 640, "tile_cache_mb": 384,
     "tile_sse": 12, "shadow_res": 2048, "cascades": 4, "aa": 2, "ssao": 1,
     "ssr": 1, "clouds": 1, "aniso": 16,
     "summary": "display-native 1536x960, 4x2048 cascades, 640 MB pool, 384 MB "
                "tile cache at screen-space error 12; expected to fail, it is "
                "there to find the ceiling"},
)


def cvars(t: dict) -> dict:
    return {
        "r.DynamicGlobalIlluminationMethod": 0,   # no Lumen
        "r.ReflectionMethod": 0,                  # no Lumen reflections
        "r.Shadow.Virtual.Enable": 0,             # no virtual shadow maps
        "r.AntiAliasingMethod": t["aa"],          # 1 FXAA, 2 TAA; never TSR
        "r.ScreenPercentage": 100,
        "r.Shadow.MaxResolution": t["shadow_res"],
        "r.Shadow.CSM.MaxCascades": t["cascades"],
        "r.AmbientOcclusionLevels": -1 if t["ssao"] else 0,
        "r.SSR.Quality": 2 if t["ssr"] else 0,
        "r.VolumetricCloud": t["clouds"],
        "r.VolumetricFog": 0,
        "r.MotionBlurQuality": 0,
        "r.BloomQuality": 2 if t["tier"] == 0 else 4,
        "r.MaxAnisotropy": t["aniso"],
        "r.Streaming.PoolSize": t["pool_mb"],
        "r.Streaming.LimitPoolSizeToVRAM": 0,     # shared memory reports nonsense
    }


def estimate_vram_mb(t: dict) -> dict:
    """ESTIMATE, not a measurement. Terms in MiB."""
    bpp = (BYTES_PER_PIXEL_BASE
           + (BYTES_PER_PIXEL_TAA if t["aa"] == 2 else 0)
           + (BYTES_PER_PIXEL_SSAO if t["ssao"] else 0)
           + (BYTES_PER_PIXEL_SSR if t["ssr"] else 0)
           + (BYTES_PER_PIXEL_CLOUD if t["clouds"] else 0))
    terms = {
        "render_targets": t["width"] * t["height"] * bpp / MIB,
        "shadow_atlas": t["shadow_res"] ** 2 * t["cascades"] * SHADOW_BYTES_PER_TEXEL / MIB,
        "texture_pool": t["pool_mb"],
        # Google tile textures arrive uncompressed and sit OUTSIDE the pool.
        "tile_cache": t["tile_cache_mb"],
        "fixed": FIXED_MB + (CLOUD_NOISE_MB if t["clouds"] else 0),
        "baked_luts": BAKED_LUT_MB,
    }
    terms = {k: round(v, 1) for k, v in terms.items()}
    terms["total"] = round(sum(terms.values()), 1)
    return terms


def launch_args(t: dict) -> list:
    """What the integrator's hook appends to the FlightSimRender command.
    ``-FlightSimStressTier=`` is inert: measure_ladder.py looks for it in the
    command line UE echoes into render.log, so an unapplied tier is refused."""
    pairs = ",".join(f"{k}={v}" for k, v in cvars(t).items())
    return ["-dx11", f"-FlightSimStressTier={t['tier']}", f"-DPCVars={pairs}"]


def build() -> dict:
    tiers = []
    for t in TIERS:
        tiers.append({
            "tier": t["tier"], "summary": t["summary"],
            "width": t["width"], "height": t["height"],
            "cvars": cvars(t),
            "tileset": {"maximum_screen_space_error": t["tile_sse"],
                        "maximum_cached_mb": t["tile_cache_mb"]},
            "launch_args": launch_args(t),
            "est_vram_mb": estimate_vram_mb(t),
            "sustained": None,   # filled only by a Windows run
        })
    return {
        "lane": "hardware_perf.stress_ladder.alpine",
        "version": 1,
        "label": "every VRAM figure is an ESTIMATE; no tier is measured or sustained",
        "scenario": {"name": "alpine", "test_scenario": 11,
                     "command": "python scripts\\run_test_scenarios.py --clip 3 --only 11"},
        "target": {"rhi": "d3d11", "display": list(DISPLAY),
                   "start_usable_vram_mb": START_USABLE_VRAM_MB,
                   "start_max_capture_width": START_MAX_CAPTURE_WIDTH},
        "protocol": {
            "runs_per_tier": 3,
            "cooldown_seconds": 60,
            "stop_at_first_failure": True,
            "thresholds": {
                "device_lost_max": 0,
                "min_frames": 8,
                # Half of Windows' default 2 s TdrDelay: a frame that needs
                # longer is within a factor of two of a driver reset.
                "frame_wall_ms_p95_max": 1000.0,
                "available_ram_mb_min": 1024.0,
                "throttle_ratio_min": 0.80,
                "temperature_c_max": 95.0,
                "black_fraction_max": 0.5,
                "luma_stddev_min": 2.0,
            },
        },
        "tiers": tiers,
    }


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUT.write_text(dumps(build()))
    for t in build()["tiers"]:
        print(f"tier {t['tier']}: {t['width']}x{t['height']}  est {t['est_vram_mb']['total']} MB (ESTIMATE)")
    print(f"wrote {OUT}")
