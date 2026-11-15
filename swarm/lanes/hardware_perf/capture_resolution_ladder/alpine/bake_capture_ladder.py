"""Offline generator (Mac): the alpine capture-resolution ladder. Visual-only.

The Intel iGPU laptop loses its D3D11 device when one frame is too heavy, so
this ladder raises what a still DELIVERS (pixels and samples per pixel)
without raising what one GPU frame costs. Every pass is a render target no
larger than 1344x864; the Mac-baked plan says where each pass looks and the
CPU resolver (resolve_capture.py) puts them together:

  tier 0  1280x800, one pass                      (today's frame; the floor)
  tier 1  1280x800, 4 rotated-grid sub-pixel passes averaged   (4x SSAA)
  tier 2  2560x1600 as 2x2 off-centre tiles with a 32 px gutter
  tier 3  2560x1600, 2x2 tiles x 4 sub-pixel passes            (16 passes)

Writes alpine_capture_ladder.json (per pass: the full-frame pixel window and
the NDC scale/offset for an off-centre projection) and blue_noise_64.r8 (a
void-and-cluster rank tile the resolver dithers with, so the averaged
thin-air sky gradient does not band at 8 bits).

    .venv/bin/python swarm/lanes/hardware_perf/capture_resolution_ladder/alpine/bake_capture_ladder.py

Every memory and time figure is an ESTIMATE. Nothing here is measured; a tier
counts as sustained only after measure_capture_gate.py ran on the laptop.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

LANE = Path(__file__).resolve().parent
PLAN = LANE / "alpine_capture_ladder.json"
NOISE = LANE / "blue_noise_64.r8"

DISPLAY = (1536, 960)                 # the laptop panel, 16:10
START_MAX_CAPTURE_WIDTH = 1280        # core/render/hardware_budget.py, unmeasured
START_USABLE_VRAM_MB = 491
#: ESTIMATE, bytes per shaded pixel on the deferred D3D11 path with TAA and
#: quarter-res clouds (same figures as the stress_ladder lane: 52 + 16 + 5).
BYTES_PER_PIXEL = 73
#: Windows' default GPU watchdog (TdrDelay) is 2 s; the gate allows half.
TDR_DELAY_MS = 2000
FRAME_MS_CEILING = 1000

#: 4x rotated-grid offsets in delivered pixels (each row and column of the
#: 4x4 sub-pixel grid is hit once).
RGSS4 = [(0.125, 0.375), (-0.375, 0.125), (0.375, -0.125), (-0.125, -0.375)]

TIERS = [
    {"tier": 0, "delivered": (1280, 800), "grid": (1, 1), "gutter": 0, "jitter": [(0.0, 0.0)]},
    {"tier": 1, "delivered": (1280, 800), "grid": (1, 1), "gutter": 0, "jitter": RGSS4},
    {"tier": 2, "delivered": (2560, 1600), "grid": (2, 2), "gutter": 32, "jitter": [(0.0, 0.0)]},
    {"tier": 3, "delivered": (2560, 1600), "grid": (2, 2), "gutter": 32, "jitter": RGSS4},
]
#: If tier 0 itself loses the device: render smaller, Lanczos up in the resolver.
STEP_DOWN_SCALES = [0.8, 0.75]        # 1024x640, 960x600


def ndc_window(window, full):
    """Pixel window (x0, y0, x1, y1) of the full frame -> (sx, sy, ox, oy) with
    x' = sx*x + ox*w and y' = sy*y + oy*w taking the window to clip [-1, 1].
    Pixel y runs down, NDC y runs up."""
    x0, y0, x1, y1 = window
    w, h = full
    return (w / (x1 - x0), h / (y1 - y0), -(x0 + x1 - w) / (x1 - x0), (y0 + y1 - h) / (y1 - y0))


def passes(tier: dict) -> list:
    w, h = tier["delivered"]
    nx, ny = tier["grid"]
    g = tier["gutter"]
    pw, ph = w // nx, h // ny
    out = []
    for j in range(ny):
        for i in range(nx):
            for s, (jx, jy) in enumerate(tier["jitter"]):
                win = (i * pw - g + jx, j * ph - g + jy, (i + 1) * pw + g + jx, (j + 1) * ph + g + jy)
                sx, sy, ox, oy = ndc_window(win, (w, h))
                out.append({
                    "index": len(out), "file": f"pass_{len(out):03d}.png",
                    "tile": [i, j], "sample": s,
                    "paste_px": [i * pw, j * ph], "window_px": list(win),
                    "ndc_scale": [sx, sy], "ndc_offset": [ox, oy],
                    "weight": 1.0 / len(tier["jitter"]),
                    # ESTIMATE: tiles stream and TAA history settles after a view change
                    "warmup_frames": 16 if s == 0 else 4,
                })
    return out


def describe(tier: dict) -> dict:
    w, h = tier["delivered"]
    nx, ny = tier["grid"]
    g = tier["gutter"]
    rw, rh = w // nx + 2 * g, h // ny + 2 * g
    ps = passes(tier)
    return {
        "tier": tier["tier"], "delivered_px": [w, h], "grid": [nx, ny], "gutter_px": g,
        "pass_render_px": [rw, rh], "payload_px": [w // nx, h // ny],
        "samples_per_pixel": len(tier["jitter"]), "pass_count": len(ps),
        "display_supersample_linear": round(w / DISPLAY[0], 4),
        "est_render_target_mb": round(rw * rh * BYTES_PER_PIXEL / 2 ** 20, 1),
        "est_gpu_frames": sum(p["warmup_frames"] + 1 for p in ps),
        "requires": (["fixed exposure", "bloom, vignette and lens drops off in tile passes",
                      "per-tile Cesium camera so tile detail follows the delivered size"]
                     if nx * ny > 1 else []) + (["paused sim between passes"] if len(ps) > 1 else []),
        "passes": ps,
    }


def blue_noise(n: int = 64, seed: int = 20261112, sigma: float = 1.5) -> np.ndarray:
    """Void-and-cluster rank tile (Ulichney 1993), n x n uint8, toroidal."""
    d = np.minimum(np.arange(n), n - np.arange(n)).astype(np.float64)
    kern = np.array([[math.exp(-(a * a + b * b) / (2 * sigma * sigma)) for b in d] for a in d])

    def splat(e, y, x, sign):
        e += sign * np.roll(np.roll(kern, y, 0), x, 1)

    rng = np.random.default_rng(seed)
    ones = n * n // 10
    on = np.zeros(n * n, bool)
    on[rng.permutation(n * n)[:ones]] = True
    on = on.reshape(n, n)
    energy = np.zeros((n, n))
    for y, x in zip(*np.nonzero(on)):
        splat(energy, y, x, 1)

    def tightest():
        return np.unravel_index(np.argmax(np.where(on, energy, -np.inf)), on.shape)

    def emptiest():
        return np.unravel_index(np.argmin(np.where(on, np.inf, energy)), on.shape)

    while True:                                   # relax the seed pattern
        c = tightest()
        on[c] = False
        splat(energy, *c, -1)
        v = emptiest()
        on[v] = True
        splat(energy, *v, 1)
        if v == c:
            break
    rank = np.zeros((n, n), np.int64)
    keep_on, keep_energy = on.copy(), energy.copy()
    for r in range(ones - 1, -1, -1):             # phase 1: peel clusters
        c = tightest()
        on[c] = False
        splat(energy, *c, -1)
        rank[c] = r
    on, energy = keep_on, keep_energy
    for r in range(ones, n * n):                  # phases 2-3: fill voids
        v = emptiest()
        on[v] = True
        splat(energy, *v, 1)
        rank[v] = r
    return (rank * 256 // (n * n)).astype(np.uint8)


def build() -> dict:
    return {
        "lane": "hardware_perf.capture_resolution_ladder.alpine",
        "label": "visual-only",
        "measured": False,
        "scenario": {"name": "alpine", "test_scenario": 11},
        "target": {"rhi": "d3d11", "display_px": list(DISPLAY),
                   "start_max_capture_width": START_MAX_CAPTURE_WIDTH,
                   "start_usable_vram_mb": START_USABLE_VRAM_MB},
        "estimate_inputs": {"bytes_per_pixel": BYTES_PER_PIXEL, "tdr_delay_ms": TDR_DELAY_MS},
        "gate": {"frame_ms_ceiling": FRAME_MS_CEILING, "gpu_mb_above_idle_ceiling": START_USABLE_VRAM_MB,
                 "temp_c_ceiling": 90.0, "seam_excess_levels_ceiling": 1.0,
                 # ESTIMATES. 0.75: four samples gave 0.63-0.67 on the synthetic ridge in the
                 # lane test. Tier 1 has no sharpness floor: supersampling
                 # rightly removes alias energy the Laplacian counts as detail. Its guard
                 # against ghosting (sim not paused, exposure drift) is the sample spread.
                 "alias_ratio_ceiling": 0.75,
                 "ground_sharpness_floor": {"2": 1.0, "3": 1.0},
                 "sample_spread_levels_ceiling": 1.0,
                 "box_coordinates": "pixels of the 1280x800 tier 0 frame"},
        "resolve": {"accumulate_in": "linear light (sRGB decoded)", "dither": NOISE.name,
                    "display_fit_filter": "lanczos", "step_down_filter": "lanczos"},
        "tier0_step_down": [{"scale": s, "pass_render_px": [round(1280 * s), round(800 * s)]}
                            for s in STEP_DOWN_SCALES],
        "tiers": [describe(t) for t in TIERS],
    }


def write(out_dir: Path = LANE) -> None:
    noise = blue_noise()
    (out_dir / NOISE.name).write_bytes(noise.tobytes())
    plan = build()
    plan["resolve"]["dither_sha256"] = hashlib.sha256(noise.tobytes()).hexdigest()
    (out_dir / PLAN.name).write_text(json.dumps(plan, indent=1) + "\n")


if __name__ == "__main__":
    write()
    for t in build()["tiers"]:
        print(f"tier {t['tier']}: {t['delivered_px']} in {t['pass_count']} passes of {t['pass_render_px']}, "
              f"render targets ~{t['est_render_target_mb']} MB (ESTIMATE)")
