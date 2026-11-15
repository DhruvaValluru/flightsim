"""Offline bake (Mac) of the alpine detail normal maps. VISUAL ONLY.

Google's photogrammetry tiles carry no relief finer than their own mesh and
photograph. This bakes two tileable, band-limited detail normal maps (rock
strata and wind-packed snow) as BC5 DDS files with a full mip chain, plus the
world scales and fade distances the tiles material needs. The laptop only
samples them: 2 texture taps at tier 0.

Everything here is procedural (seeded Fourier synthesis); nothing is fetched.
No render or pixel result comes from this file: that is measured on the
Windows laptop (INTEGRATION.md, "Pixel gate").

    .venv/bin/python swarm/lanes/terrain/detail_normals/alpine/bake_alpine_detail_normals.py
    ... --tier 2            # heavier tiers, written on demand (not committed)
    ... --png               # also write top-mip PNGs (import fallback)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import zlib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
SEED = 20261112

# ---------------------------------------------------------------- the look
#: The capture the fade distances are computed for (the laptop budget's
#: max_capture_width, the display's 1.6 aspect, the card camera's hfov).
CAPTURE_WIDTH_PX = 1280
CAPTURE_HEIGHT_PX = 800
HFOV_DEG = 54.4

#: Layers. ``band`` is in cycles per tile; ``tile_m`` is one repeat on the
#: ground. ``rms_slope`` is the root-mean-square |grad h| of the baked surface.
LAYERS = {
    "rock": {
        "band": (8.0, 64.0), "beta": 1.7, "stretch": (1.0, 0.38), "ridged": 0.55,
        "rms_slope": 0.25, "tile_m": 48.0, "far_tile_m": 311.0, "seed": 1,
    },
    "snow": {
        "band": (8.0, 64.0), "beta": 2.2, "stretch": (0.22, 1.0), "ridged": 0.0,
        "rms_slope": 0.10, "tile_m": 96.0, "far_tile_m": None, "seed": 2,
    },
}

#: Texture edge per tier: (rock, snow). Taps = texture samples per pixel.
TIERS = {
    0: {"rock": 512, "snow": 256, "taps": 2, "projection": "dominant-axis",
        "far_layer": False, "summary": "rock 512 + snow 256, one projection, near layer only"},
    1: {"rock": 1024, "snow": 512, "taps": 3, "projection": "dominant-axis",
        "far_layer": True, "summary": "rock 1024 + snow 512, adds the 311 m rock layer"},
    2: {"rock": 2048, "snow": 1024, "taps": 6, "projection": "biplanar",
        "far_layer": True, "summary": "rock 2048 + snow 1024, biplanar (no projection seams), height/slope snow mask"},
    3: {"rock": 2048, "snow": 2048, "taps": 9, "projection": "triplanar",
        "far_layer": True, "summary": "2048 both, triplanar, roughness from mip normal length"},
}

#: Snow mask from the tile photograph (tier 0 and 1): luminance and saturation
#: smoothstep edges on the tile's base colour (display-referred, 0..1).
SNOW_MASK = {"lum_lo": 0.55, "lum_hi": 0.75, "sat_lo": 0.12, "sat_hi": 0.25}


# ------------------------------------------------------------- synthesis
def synth_height(n: int, layer: dict) -> np.ndarray:
    """A tileable height field (n x n, zero mean, unit variance).

    Random phases under a power-law amplitude ``k^-beta`` inside ``band``
    (cycles per tile), with an anisotropic stretch. Built in the Fourier
    domain, so it wraps exactly. The spectrum is defined in cycles per tile,
    so every resolution carries the same surface (larger n only adds headroom).
    """
    rng = np.random.default_rng(SEED + layer["seed"])
    k_max = 96  # phases are drawn on a fixed lattice so all tiers share one surface
    freqs = np.fft.fftfreq(2 * k_max, d=1.0 / (2 * k_max))  # integer cycles, -k_max..k_max-1
    fx, fy = np.meshgrid(freqs, freqs, indexing="xy")
    sx, sy = layer["stretch"]
    k = np.hypot(fx / sx, fy / sy)
    lo, hi = layer["band"]
    with np.errstate(divide="ignore"):
        amp = np.where(k > 0, k ** (-layer["beta"]), 0.0)
    # smooth band edges (raised cosine over half an octave) keep the band limit
    amp *= _edge(k, lo * 0.7, lo) * (1.0 - _edge(k, hi, hi * 1.4))
    # the lattice Nyquist row/column has no conjugate partner: drop it
    amp[np.abs(fx) >= k_max] = 0.0
    amp[np.abs(fy) >= k_max] = 0.0
    phase = rng.uniform(0.0, 2.0 * math.pi, size=amp.shape)
    spec_small = amp * np.exp(1j * phase)
    spec = np.zeros((n, n), dtype=complex)
    idx = freqs.astype(int) % n
    spec[np.ix_(idx, idx)] = spec_small
    h = np.fft.ifft2(spec).real
    h = (h - h.mean()) / h.std()
    if layer["ridged"] > 0.0:
        ridged = 1.0 - 2.0 * np.abs(np.tanh(h))
        ridged = (ridged - ridged.mean()) / ridged.std()
        h = (1.0 - layer["ridged"]) * h + layer["ridged"] * ridged
        h = (h - h.mean()) / h.std()
    return h


def _edge(x: np.ndarray, a: float, b: float) -> np.ndarray:
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(math.pi * t)


def normals_from_height(h: np.ndarray, rms_slope: float) -> np.ndarray:
    """Unit normals (n, n, 3) of ``h`` rescaled so RMS |grad h| = rms_slope.

    Periodic central differences: the result wraps like the height does.
    """
    n = h.shape[0]
    dx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) * 0.5 * n
    dy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) * 0.5 * n
    scale = rms_slope / math.sqrt(float(np.mean(dx * dx + dy * dy)))
    v = np.stack([-dx * scale, -dy * scale, np.ones_like(h)], axis=-1)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def mip_chain(normals: np.ndarray) -> list:
    """Box-filtered, renormalised mips down to 1x1. Returns (unit normals,
    mean pre-normalisation length) per level; the length is the Toksvig
    input tier 3 turns into roughness."""
    chain = [(normals, 1.0)]
    cur = normals
    while cur.shape[0] > 1:
        m = cur.shape[0] // 2
        avg = cur.reshape(m, 2, m, 2, 3).mean(axis=(1, 3))
        length = np.linalg.norm(avg, axis=-1, keepdims=True)
        cur = avg / np.maximum(length, 1e-9)
        chain.append((cur, float(length.mean())))
    return chain


def encode_xy(normals: np.ndarray) -> np.ndarray:
    """(n, n, 2) uint8: x and y as UNORM, 128 = 0 (128/255 reads back +0.002)."""
    return np.clip(np.rint(normals[..., :2] * 127.5 + 127.5), 0, 255).astype(np.uint8)


# ------------------------------------------------------------------- BC5
def _bc4_blocks(channel: np.ndarray) -> np.ndarray:
    """BC4 (one BC5 half) of a (H, W) uint8 image, H and W multiples of 4.
    Endpoints are the block's max and min (8-value mode). Returns (blocks, 8)."""
    hgt, wid = channel.shape
    b = channel.reshape(hgt // 4, 4, wid // 4, 4).transpose(0, 2, 1, 3).reshape(-1, 16).astype(np.int32)
    e0 = b.max(axis=1)
    e1 = b.min(axis=1)
    span = np.maximum(e0 - e1, 1)
    pos = np.rint((e0[:, None] - b) * 7.0 / span[:, None]).astype(np.int64)  # 0 = e0 .. 7 = e1
    idx = np.where(pos == 0, 0, np.where(pos == 7, 1, pos + 1))
    idx[e0 == e1] = 0
    bits = np.zeros(len(b), dtype=np.uint64)
    for i in range(16):
        bits |= idx[:, i].astype(np.uint64) << np.uint64(3 * i)
    out = np.empty((len(b), 8), dtype=np.uint8)
    out[:, 0] = e0
    out[:, 1] = e1
    for i in range(6):
        out[:, 2 + i] = ((bits >> np.uint64(8 * i)) & np.uint64(0xFF)).astype(np.uint8)
    return out


def bc5_encode(xy: np.ndarray) -> bytes:
    """BC5_UNORM bytes of a (H, W, 2) uint8 image (edges replicated to 4)."""
    hgt, wid = xy.shape[:2]
    ph, pw = (-hgt) % 4, (-wid) % 4
    if ph or pw:
        xy = np.pad(xy, ((0, ph), (0, pw), (0, 0)), mode="edge")
    return np.concatenate([_bc4_blocks(xy[..., 0]), _bc4_blocks(xy[..., 1])], axis=1).tobytes()


def bc5_decode(data: bytes, height: int, width: int) -> np.ndarray:
    """The reference decoder (the D3D11 BC4 rules), used by the test."""
    bh, bw = (height + 3) // 4, (width + 3) // 4
    raw = np.frombuffer(data, dtype=np.uint8).reshape(bh * bw, 16)
    out = np.empty((bh * 4, bw * 4, 2), dtype=np.uint8)
    for c in range(2):
        blk = raw[:, c * 8:(c + 1) * 8]
        e0 = blk[:, 0].astype(np.float64)
        e1 = blk[:, 1].astype(np.float64)
        bits = np.zeros(len(blk), dtype=np.uint64)
        for i in range(6):
            bits |= blk[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
        pal = np.empty((len(blk), 8))
        pal[:, 0], pal[:, 1] = e0, e1
        eight = e0 > e1
        for i in range(2, 8):
            p8 = ((8 - i) * e0 + (i - 1) * e1) / 7.0
            p6 = ((6 - i) * e0 + (i - 1) * e1) / 5.0 if i < 6 else (0.0 if i == 6 else 255.0)
            pal[:, i] = np.where(eight, p8, p6)
        vals = np.empty((len(blk), 16))
        for i in range(16):
            sel = ((bits >> np.uint64(3 * i)) & np.uint64(7)).astype(np.int64)
            vals[:, i] = pal[np.arange(len(blk)), sel]
        out[..., c] = np.rint(vals).astype(np.uint8).reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(bh * 4, bw * 4)
    return out[:height, :width]


DXGI_FORMAT_BC5_UNORM = 83


def dds_bc5(mips_xy: list) -> bytes:
    """A DDS (DX10 header) holding the BC5 mip chain."""
    hgt, wid = mips_xy[0].shape[:2]
    payload = [bc5_encode(m) for m in mips_xy]
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000
    header = struct.pack("<7I", 124, flags, hgt, wid, len(payload[0]), 0, len(payload))
    header += b"\0" * 44
    header += struct.pack("<2I4s5I", 32, 0x4, b"DX10", 0, 0, 0, 0, 0)
    header += struct.pack("<5I", 0x1000 | 0x8 | 0x400000, 0, 0, 0, 0)
    assert len(header) == 124
    dx10 = struct.pack("<5I", DXGI_FORMAT_BC5_UNORM, 3, 0, 1, 0)
    return b"DDS " + header + dx10 + b"".join(payload)


def png_rgb(rgb: np.ndarray) -> bytes:
    """A minimal 8-bit RGB PNG writer (no Pillow on the bake machine)."""
    hgt, wid = rgb.shape[:2]
    raw = np.concatenate([np.zeros((hgt, 1), dtype=np.uint8), rgb.reshape(hgt, wid * 3)], axis=1).tobytes()

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", wid, hgt, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# ------------------------------------------------------- render-side numbers
def footprint_m_per_px(distance_m: float) -> float:
    """Ground distance one pixel spans, facing the camera, at ``distance_m``."""
    return 2.0 * distance_m * math.tan(math.radians(HFOV_DEG) / 2.0) / CAPTURE_WIDTH_PX


def fade_distances(tile_m: float, band: tuple) -> dict:
    """Where a layer stops being resolvable in the capture.

    ``fade_end_m``: the layer's longest wavelength (tile / band_lo) spans two
    pixels (its Nyquist limit); past it the layer is pure aliasing, so its
    strength is exactly 0 there. ``fade_start_m`` is a quarter of that."""
    longest = tile_m / band[0]
    end = (longest / 2.0) / footprint_m_per_px(1.0)
    return {"tile_m": tile_m, "wavelength_m": [round(tile_m / band[1], 4), round(longest, 4)],
            "fade_start_m": round(end / 4.0, 1), "fade_end_m": round(end, 1)}


def vram_mb(edge: int) -> float:
    """ESTIMATE: BC5 is 1 byte per texel; a full mip chain adds one third."""
    return edge * edge * 4.0 / 3.0 / (1024.0 * 1024.0)


def tier_plan(tier: int) -> dict:
    t = TIERS[tier]
    plan = {"tier": tier, "summary": t["summary"], "texture_taps_per_pixel": t["taps"],
            "projection": t["projection"], "rock_px": t["rock"], "snow_px": t["snow"],
            "est_vram_mb": round(vram_mb(t["rock"]) + vram_mb(t["snow"]), 3),
            "layers": {"rock_near": fade_distances(LAYERS["rock"]["tile_m"], LAYERS["rock"]["band"]),
                       "snow": fade_distances(LAYERS["snow"]["tile_m"], LAYERS["snow"]["band"])}}
    if t["far_layer"]:
        plan["layers"]["rock_far"] = fade_distances(LAYERS["rock"]["far_tile_m"], (16.0, LAYERS["rock"]["band"][1]))
    return plan


def bake_layer(name: str, edge: int) -> dict:
    layer = LAYERS[name]
    normals = normals_from_height(synth_height(edge, layer), layer["rms_slope"])
    chain = mip_chain(normals)
    mips_xy = [encode_xy(m) for m, _ in chain]
    return {"name": name, "edge": edge, "normals": normals, "mips_xy": mips_xy,
            "dds": dds_bc5(mips_xy), "mean_nz": float(normals[..., 2].mean()),
            "mip_normal_length": [round(length, 5) for _, length in chain]}


def build(tier: int = 0, out_dir: Path = OUT, write_png: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = tier_plan(tier)
    files = {}
    for name in ("rock", "snow"):
        baked = bake_layer(name, TIERS[tier][name])
        fname = f"alpine_detail_{name}_t{tier}.dds"
        (out_dir / fname).write_bytes(baked["dds"])
        files[fname] = hashlib.sha256(baked["dds"]).hexdigest()
        if write_png:
            xy = baked["mips_xy"][0]
            z = np.clip(np.rint(baked["normals"][..., 2] * 127.5 + 127.5), 0, 255).astype(np.uint8)
            (out_dir / f"alpine_detail_{name}_t{tier}.png").write_bytes(png_rgb(np.dstack([xy, z])))
        plan[name] = {"file": fname, "format": "BC5_UNORM (DXGI 83), xy; z = sqrt(1 - x^2 - y^2)",
                      "mips": len(baked["mips_xy"]), "rms_slope": LAYERS[name]["rms_slope"],
                      "mean_nz": round(baked["mean_nz"], 5),
                      "mip_normal_length": baked["mip_normal_length"]}
    plan.update({
        "label": "visual-only", "seed": SEED,
        "capture": {"width_px": CAPTURE_WIDTH_PX, "height_px": CAPTURE_HEIGHT_PX, "hfov_deg": HFOV_DEG,
                    "footprint_m_per_px_at_1km": round(footprint_m_per_px(1000.0), 4)},
        "snow_mask": SNOW_MASK,
        "sastrugi_long_axis": "+U of the snow map; the material rotates it onto the wind bearing",
        "diffuse_energy_shift": {"rock": round(plan["rock"]["mean_nz"] - 1.0, 5),
                                 "snow": round(plan["snow"]["mean_nz"] - 1.0, 5),
                                 "note": "mean N.z - 1 at full strength: how much flat sunlit ground darkens"},
        "files_sha256": files,
    })
    (out_dir / f"alpine_detail_t{tier}.json").write_text(json.dumps(plan, indent=1) + "\n")
    return plan


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tier", type=int, choices=sorted(TIERS), default=0)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--png", action="store_true")
    args = ap.parse_args()
    plan = build(args.tier, args.out, args.png)
    print(json.dumps({k: plan[k] for k in ("tier", "est_vram_mb", "layers", "files_sha256")}, indent=1))


if __name__ == "__main__":
    main()
