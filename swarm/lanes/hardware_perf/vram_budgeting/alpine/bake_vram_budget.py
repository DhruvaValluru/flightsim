"""Alpine VRAM ledger for the integrated-GPU laptop (D3D11, shared memory).

Offline, stdlib only, deterministic. Splits the usable-VRAM cap from
core/render/hardware_budget.py into named consumers (render targets, shadow
maps, Cesium/Google tile cache, UE streaming pool, baked LUTs, fixed overhead)
and writes one cvar/tileset setting block per tier.

Every byte count here is ARITHMETIC ON ASSUMED FORMATS, an ESTIMATE. Nothing
in this file is a measurement and no tier is claimed to be sustained; the
Windows run in INTEGRATION.md is what measures.

    python3 swarm/lanes/hardware_perf/vram_budgeting/alpine/bake_vram_budget.py
    python3 .../bake_vram_budget.py --usable-vram-mb 491 --scan-lanes
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MB = 1024 * 1024
USABLE_VRAM_MB = 491        # starting budget handed to this lane (unmeasured)
DEVICE_LOSS_MARGIN = 0.10   # tier 0 must leave this fraction of the cap unused

# bits per pixel; BC formats are 4x4 blocks (BC1/BC4 8 bytes, BC3/BC5/BC7 16)
BPP = {"RGBA8": 32, "RGBA16F": 64, "R8": 8, "R16F": 16, "RG16": 32, "D16": 16,
       "D32S8": 64, "A2B10G10R10": 32, "R11G11B10F": 32}
BLOCK_BYTES = {"BC1": 8, "BC4": 8, "BC3": 16, "BC5": 16, "BC7": 16}

# Internal-resolution targets of the UE deferred path on D3D11, bytes/pixel.
# ESTIMATE from the formats named; the real set depends on the engine build.
RT_INTERNAL = (
    ("SceneColor FloatRGBA", 8.0), ("SceneDepthZ D32S8 (R32G8X24)", 8.0),
    ("GBufferA-D 4x 32bpp", 16.0), ("Velocity RG16", 4.0),
    ("TAA history FloatRGBA", 8.0), ("post chain scratch", 12.0),
    ("bloom/downsample chain (1/3 of FloatRGBA)", 8.0 / 3),
    ("HZB R16F mips", 2.0 / 3), ("SSAO R8", 1.0), ("light attenuation", 4.0),
)
RT_OUTPUT = (("swap chain 2x RGBA8", 8.0),)


def mip_chain_bytes(w: int, h: int, fmt: str, mips: bool = True, depth: int = 1) -> int:
    """Exact byte size of a texture (full mip chain unless mips=False)."""
    total = 0
    while True:
        if fmt in BLOCK_BYTES:
            total += ((w + 3) // 4) * ((h + 3) // 4) * BLOCK_BYTES[fmt] * depth
        else:
            total += w * h * depth * BPP[fmt] // 8
        if not mips or (w == 1 and h == 1 and depth == 1):
            return total
        w, h, depth = max(1, w // 2), max(1, h // 2), max(1, depth // 2)


def render_target_bytes(width: int, height: int, screen_pct: int) -> int:
    s = (screen_pct / 100.0) ** 2
    px = width * height
    return int(px * s * sum(b for _, b in RT_INTERNAL) + px * sum(b for _, b in RT_OUTPUT))


# Tier knobs. Tier 0 is sized to fit under the cap with the margin; 1-3 are
# deliberately heavier rungs for the stress ladder and may exceed the cap.
# Alpine reasoning: snow and rock are low-frequency albedo, so a coarser tile
# screen-space error costs less here than over a city, while long ridge
# sight lines and hard snow shadows make output resolution and the first
# shadow cascade the things worth paying for.
TIERS = (
    {"tier": 0, "width": 1280, "height": 800, "screen_pct": 100, "csm_res": 1024, "csm_cascades": 1,
     "cesium_cache_mb": 160, "cesium_sse": 24.0, "cesium_tile_loads": 4, "stream_pool_mb": 128},
    {"tier": 1, "width": 1280, "height": 800, "screen_pct": 100, "csm_res": 1024, "csm_cascades": 2,
     "cesium_cache_mb": 224, "cesium_sse": 16.0, "cesium_tile_loads": 6, "stream_pool_mb": 160},
    {"tier": 2, "width": 1536, "height": 960, "screen_pct": 100, "csm_res": 2048, "csm_cascades": 2,
     "cesium_cache_mb": 320, "cesium_sse": 12.0, "cesium_tile_loads": 8, "stream_pool_mb": 256},
    {"tier": 3, "width": 1536, "height": 960, "screen_pct": 100, "csm_res": 2048, "csm_cascades": 3,
     "cesium_cache_mb": 512, "cesium_sse": 8.0, "cesium_tile_loads": 12, "stream_pool_mb": 384},
)
BAKED_LUT_ALLOWANCE_MB = 16   # sky/AP/exposure/wear LUTs from sibling alpine lanes
FIXED_OVERHEAD_MB = 48        # shaders, uniform/vertex buffers, UI, engine textures


def tier_ledger(t: dict) -> dict:
    rt = render_target_bytes(t["width"], t["height"], t["screen_pct"])
    shadow = mip_chain_bytes(t["csm_res"], t["csm_res"], "D16", mips=False) * t["csm_cascades"]
    consumers = {
        "render_targets": rt, "shadow_maps": shadow,
        "cesium_tile_cache": t["cesium_cache_mb"] * MB,
        "ue_streaming_pool": t["stream_pool_mb"] * MB,
        "baked_luts": BAKED_LUT_ALLOWANCE_MB * MB, "fixed_overhead": FIXED_OVERHEAD_MB * MB,
    }
    total = sum(consumers.values())
    rt_mb = -(-rt // MB)
    return {
        "tier": t["tier"],
        "capture": {"width": t["width"], "height": t["height"]},
        "est_bytes": consumers,
        "est_vram_mb": round(total / MB, 1),
        "cvars": {
            "r.ScreenPercentage": t["screen_pct"],
            "r.Streaming.PoolSize": t["stream_pool_mb"],
            "r.Streaming.LimitPoolSizeToVRAM": 1,
            "r.RenderTargetPoolMin": rt_mb,  # stop the RT pool hoarding freed targets
            "r.Shadow.MaxCSMResolution": t["csm_res"],
            "r.Shadow.CSM.MaxCascades": t["csm_cascades"],
            "r.DynamicGlobalIlluminationMethod": 0,
        },
        "cesium_tileset": {
            "MaximumCachedBytes": t["cesium_cache_mb"] * MB,
            "MaximumScreenSpaceError": t["cesium_sse"],
            "MaximumSimultaneousTileLoads": t["cesium_tile_loads"],
            "EnableFrustumCulling": True, "EnableFogCulling": True,
        },
        "sustained": None,  # only a Windows stress run may set this
    }


def build(usable_vram_mb: int = USABLE_VRAM_MB) -> dict:
    cap0 = usable_vram_mb * (1.0 - DEVICE_LOSS_MARGIN)
    tiers = [tier_ledger(t) for t in TIERS]
    for t in tiers:
        t["fits_cap_estimate"] = t["est_vram_mb"] <= usable_vram_mb
    if tiers[0]["est_vram_mb"] > cap0:
        raise SystemExit(f"tier 0 estimate {tiers[0]['est_vram_mb']} MB exceeds {cap0:.0f} MB "
                         f"({usable_vram_mb} MB less the {DEVICE_LOSS_MARGIN:.0%} margin)")
    tile_rgba8 = mip_chain_bytes(512, 512, "RGBA8")
    tile_bc1 = mip_chain_bytes(512, 512, "BC1")
    return {
        "version": 1, "scenario": "alpine", "lane": "hardware_perf.vram_budgeting.alpine",
        "label": "ESTIMATE: arithmetic on assumed formats; UNMEASURED on the render machine",
        "measured": False,
        "usable_vram_mb": usable_vram_mb,
        "device_loss_margin": DEVICE_LOSS_MARGIN,
        "tier0_cap_mb": round(cap0, 1),
        "render_target_model": {
            "internal_bytes_per_px": round(sum(b for _, b in RT_INTERNAL), 3),
            "output_bytes_per_px": sum(b for _, b in RT_OUTPUT),
            "internal": [list(x[:1]) + [round(x[1], 3)] for x in RT_INTERNAL],
            "output": [list(x) for x in RT_OUTPUT],
        },
        "tile_texture_bytes_512": {"RGBA8_mipped": tile_rgba8, "BC1_mipped": tile_bc1,
                                   "ratio": round(tile_rgba8 / tile_bc1, 2)},
        "tiers": tiers,
    }


def ini_text(tier: dict) -> str:
    lines = [f"; alpine VRAM tier {tier['tier']} - ESTIMATE {tier['est_vram_mb']} MB, UNMEASURED",
             "[SystemSettings]"]
    lines += [f"{k}={v}" for k, v in tier["cvars"].items()]
    return "\n".join(lines) + "\n"


def scan_lanes(root: Path) -> dict:
    """Bytes on disk of baked textures in sibling alpine lanes (informational)."""
    exts = {".rgba16f", ".dds", ".png", ".exr", ".raw", ".r8", ".bin", ".tga"}
    out = {}
    for p in sorted(root.glob("*/*/alpine/**/*")):
        if p.is_file() and p.suffix.lower() in exts:
            key = "/".join(p.relative_to(root).parts[:2])
            out[key] = out.get(key, 0) + p.stat().st_size
    return out


def write(out_dir: Path = HERE, usable_vram_mb: int = USABLE_VRAM_MB) -> dict:
    data = build(usable_vram_mb)
    files = {"alpine_vram_budget.json": json.dumps(data, indent=1, sort_keys=True) + "\n"}
    for t in data["tiers"]:
        files[f"alpine_vram_tier{t['tier']}.ini"] = ini_text(t)
    hashes = {}
    for name, text in files.items():
        (out_dir / name).write_text(text)
        hashes[name] = hashlib.sha256(text.encode()).hexdigest()
    return hashes


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--usable-vram-mb", type=int, default=USABLE_VRAM_MB)
    ap.add_argument("--out", type=Path, default=HERE)
    ap.add_argument("--scan-lanes", action="store_true")
    a = ap.parse_args()
    for n, h in write(a.out, a.usable_vram_mb).items():
        print(h, n)
    if a.scan_lanes:
        found = scan_lanes(HERE.parents[2])
        print(json.dumps({k: round(v / MB, 2) for k, v in found.items()}, indent=1),
              f"total_mb={sum(found.values()) / MB:.2f} allowance_mb={BAKED_LUT_ALLOWANCE_MB}")
