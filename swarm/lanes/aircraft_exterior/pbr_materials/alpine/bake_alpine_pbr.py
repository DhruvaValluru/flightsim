"""Offline bake (Mac) of the alpine aircraft detail pack and oil-canning normal.

    .venv/bin/python swarm/lanes/aircraft_exterior/pbr_materials/alpine/bake_alpine_pbr.py --tier 0
    .venv/bin/python .../bake_alpine_pbr.py --tier all --out <dir>

Writes, per tier, under <out>/tier<N>/:
    T_AlpineDetail_<size>.png   RGBA8, linear (UE: sRGB off, TC_Masks)
    T_AlpineNormal_<size>.png   RGB8 tangent-space normal, DirectX (green down),
                                slopes stored x NORMAL_STORE_GAIN (tier >= 1)
and <out>/bake_manifest.json (sha256 of the raw pixels and of each PNG) plus
<out>/render_tiers.json (the render-side description).

Everything is generated from a fixed seed with numpy's PCG64: no fetched
asset, no third-party code. All noise is filtered in the Fourier domain, so
every channel tiles exactly. VISUAL-ONLY.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import alpine_pbr_look as look  # noqa: E402

SEED = 20261112
MANIFEST_SCHEMA = "flightsim-swarm-alpine-pbr-bake/1"


def _freqs(n):
    f = np.fft.fftfreq(n) * n            # cycles per tile
    return np.meshgrid(f, f, indexing="xy")   # fu (along x/U), fv (along y/V)


def spectral_noise(rng, n, shape_fn):
    """Periodic noise: white noise shaped by shape_fn(fu, fv) -> gain."""
    white = np.fft.fft2(rng.standard_normal((n, n)))
    fu, fv = _freqs(n)
    gain = shape_fn(fu, fv)
    gain[0, 0] = 0.0
    return np.real(np.fft.ifft2(white * gain))


def band(fu, fv, lo, hi, beta):
    r = np.hypot(fu, fv)
    g = np.where((r >= lo) & (r <= hi), np.maximum(r, 1.0) ** (-beta), 0.0)
    return g


def equalise(x):
    """Rank-equalise to a uniform 0..1 histogram (mean 0.5, and a threshold
    at 1 - c selects an area fraction c)."""
    flat = x.ravel()
    order = np.argsort(flat, kind="stable")
    ranks = np.empty(flat.size, dtype=np.float64)
    ranks[order] = (np.arange(flat.size) + 0.5) / flat.size
    return ranks.reshape(x.shape)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def detail_pack(n, seed=SEED):
    """float64 (n, n, 4) in 0..1: R roughness breakup, G grime streaks,
    B frost threshold noise, A albedo modulation. Feature frequencies are in
    cycles per tile, so every tier shows the same pattern at a finer grain."""
    rng = np.random.default_rng(seed)
    top = n / 2.0
    # R: broad 1/f^1.5 breakup, uniform so it never shifts the mean roughness
    r = equalise(spectral_noise(rng, n, lambda fu, fv: band(fu, fv, 1, min(64, top), 1.5)))
    # G: streaks along U (low U frequency, high V frequency), sparse
    g_raw = spectral_noise(
        rng, n, lambda fu, fv: np.exp(-(fu / 2.5) ** 2) * band(0 * fu, fv, 3, min(56, top), 0.6))
    patches = equalise(spectral_noise(rng, n, lambda fu, fv: band(fu, fv, 1, 4, 1.0)))
    g = smoothstep(0.62, 0.95, equalise(g_raw)) * smoothstep(0.25, 0.75, patches)
    # B: crystalline high-frequency grain gathered into low-frequency patches
    grain = equalise(spectral_noise(rng, n, lambda fu, fv: band(fu, fv, min(24, top / 2), top, 0.0)))
    drift = equalise(spectral_noise(rng, n, lambda fu, fv: band(fu, fv, 1, 6, 1.2)))
    b = equalise(0.45 * grain + 0.55 * drift)
    # A: very low frequency tone drift between panels
    a = equalise(spectral_noise(rng, n, lambda fu, fv: band(fu, fv, 1, 8, 2.0)))
    return np.stack([r, g, b, a], axis=-1)


def oilcan_height_cm(n, seed=SEED):
    """Periodic height field in cm: one shallow dish per panel bay (zero on
    every bay edge, so it tiles and the frames stay proud), mostly inward."""
    rng = np.random.default_rng(seed + 1)
    amp = rng.uniform(-1.0, 0.3, size=(look.BAYS_V, look.BAYS_U))
    u = (np.arange(n) + 0.5) / n * look.BAYS_U
    v = (np.arange(n) + 0.5) / n * look.BAYS_V
    cu, cv = np.floor(u).astype(int), np.floor(v).astype(int)
    su, sv = np.sin(np.pi * (u - cu)), np.sin(np.pi * (v - cv))
    dish = amp[cv][:, cu] * np.outer(sv, su)
    return look.OILCAN_DEPTH_CM * dish


def normal_map(n, seed=SEED):
    """float64 (n, n, 3) unit normals with slopes x NORMAL_STORE_GAIN,
    DirectX convention (+Y down the image)."""
    h = oilcan_height_cm(n, seed)
    texel_cm = look.TILE_CM / n
    dhdx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) / (2.0 * texel_cm)
    dhdy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) / (2.0 * texel_cm)
    sx, sy = -dhdx * look.NORMAL_STORE_GAIN, -dhdy * look.NORMAL_STORE_GAIN
    inv = 1.0 / np.sqrt(sx * sx + sy * sy + 1.0)
    # image rows run down, UE's green channel points down too: no flip of sy
    return np.stack([sx * inv, sy * inv, inv], axis=-1)


def to_u8(x, rng=None):
    """Quantise 0..1 to 8 bits; with rng, +-0.5 LSB dither (the normal map's
    slopes are a few LSB, so undithered rounding would band)."""
    y = x * 255.0
    if rng is not None:
        y = y + rng.uniform(-0.5, 0.5, size=x.shape)
    return np.clip(np.rint(y), 0, 255).astype(np.uint8)


def bake_tier(tier_row, seed=SEED):
    """{name: uint8 array} for one tier."""
    n = tier_row["size"]
    out = {f"T_AlpineDetail_{n}": to_u8(detail_pack(n, seed))}
    if tier_row["normal_map"]:
        rng = np.random.default_rng(seed + 2)
        out[f"T_AlpineNormal_{n}"] = to_u8(normal_map(n, seed) * 0.5 + 0.5, rng)
    return out


def pixel_sha256(arr):
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


UE_IMPORT = {
    "T_AlpineDetail": {"srgb": False, "compression": "TC_Masks", "mips": "FromTextureGroup",
                       "address": "Wrap", "lod_group": "TEXTUREGROUP_World"},
    "T_AlpineNormal": {"srgb": False, "compression": "TC_Normalmap", "mips": "FromTextureGroup",
                       "address": "Wrap", "flip_green": False, "lod_group": "TEXTUREGROUP_WorldNormalMap"},
}


def main(argv=None):
    from PIL import Image

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tier", default="0", help="0..3 or all")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    args = ap.parse_args(argv)
    rows = look.tier_table()
    wanted = rows if args.tier == "all" else [rows[int(args.tier)]]
    os.makedirs(args.out, exist_ok=True)
    manifest_path = os.path.join(args.out, "bake_manifest.json")
    manifest = {"schema": MANIFEST_SCHEMA, "lane": look.LANE_ID, "seed": SEED,
                "generator": "bake_alpine_pbr.py", "numpy": np.__version__,
                "visual_only": True, "textures": {}}
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            old = json.load(f)
        if old.get("schema") == MANIFEST_SCHEMA and old.get("seed") == SEED:
            manifest["textures"] = old.get("textures", {})
    for row in wanted:
        folder = os.path.join(args.out, f"tier{row['tier']}")
        os.makedirs(folder, exist_ok=True)
        for name, arr in bake_tier(row).items():
            path = os.path.join(folder, name + ".png")
            Image.fromarray(arr).save(path, optimize=True)
            manifest["textures"][f"tier{row['tier']}/{name}.png"] = {
                "tier": row["tier"], "size": row["size"], "channels": int(arr.shape[2]),
                "pixel_sha256": pixel_sha256(arr), "file_sha256": file_sha256(path),
                "ue_import": UE_IMPORT[name.rsplit("_", 1)[0]],
                "licence": "generated by this repository's own code; no third-party input",
            }
            print(f"wrote {path}")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
        f.write("\n")
    with open(os.path.join(args.out, "render_tiers.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": look.SCHEMA, "lane": look.LANE_ID, "visual_only": True,
                   "tiers": rows, "albedo_range": look.ALBEDO_RANGE,
                   "max_darkening": look.MAX_DARKENING, "alpine_scalars": look.ALPINE_SCALARS,
                   "tile_cm": look.TILE_CM, "normal_store_gain": look.NORMAL_STORE_GAIN,
                   "shared_params": look.SHARED_PARAMS,
                   "status": look.UNCALIBRATED}, f, indent=1, sort_keys=True)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
