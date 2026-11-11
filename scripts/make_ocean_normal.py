#!/usr/bin/env python3
"""Generate the beauty ocean's tileable wave normal map
(assets/terrain_detail/ocean/ocean_normal_512.png), this project's own
output, dedicated CC0-1.0 (THIRD_PARTY_VISUAL.md "Terrain and ocean detail").

Lane B of the non-urban visual push (2026-11-11). No CC0 water normal map
with a clear provenance exists on Poly Haven or ambientCG (both searched
2026-11-11: no water normals), so the map is synthesised the way ocean
renderers do (Tessendorf 2001, "Simulating Ocean Water"): a Phillips
spectrum over a periodic patch, random Gaussian amplitudes, and the
surface slope field from the inverse FFT of i k h(k). Periodic by
construction, so the tile repeats seamlessly. Pure standard library
(a radix-2 FFT below), deterministic from SEED.

    python3 scripts/make_ocean_normal.py [--out assets/terrain_detail/ocean]

Writes ocean_normal_512.png (RGB 8-bit, OpenGL convention: green = slope
toward image-up, like Poly Haven's nor_gl maps) and ocean_normal.json
(the parameters, the measured slope statistics M_FlightSimOceanBeauty
reads, and the decoded pixels' sha256 so a different zlib that changes
the PNG bytes is caught as a pixel change or not). The PNG's own sha256
is pinned in assets/terrain_detail/PIN.json.
"""
from __future__ import annotations

import argparse
import cmath
import hashlib
import json
import math
import random
import struct
import zlib
from pathlib import Path

SIZE = 512                 # texels per side
PATCH_M = 256.0            # metres the tile spans (0.5 m per texel)
WIND_MS = 10.0             # the spectrum's wind (sets the peak, L = V^2 / g)
WIND_DIR = (1.0, 0.0)      # +u
SEED = 20261111
G = 9.81
#: Waves against the wind are damped to this share (Tessendorf's directional
#: suppression; a pure |k.w|^2 makes an unrealistically standing sea).
AGAINST_WIND = 0.25
#: Waves shorter than this many texels are cut (no aliasing in the top mip).
MIN_TEXELS_PER_WAVE = 4.0
#: The directional spread |cos|^SPREAD_POWER (Phillips' own is 2). A narrower
#: spread (stated choice) so the crests read across the wind, not as noise.
SPREAD_POWER = 4.0
#: The spectrum's amplitude is arbitrary (Phillips' A), so the slope field is
#: normalised: the encoded slopes have this RMS (|(dh/du, dh/dv)|). The shader
#: scales the decoded slope to the sea state it draws (Cox & Munk 1954);
#: ocean_normal.json carries the RMS so it can.
TARGET_RMS_ENCODED = 0.35


def fft(a, invert=False):
    """In-place iterative radix-2 FFT of a list of complex numbers."""
    n = len(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    while length <= n:
        ang = (2.0 * math.pi / length) * (1.0 if invert else -1.0)
        wl = cmath.exp(1j * ang)
        half = length // 2
        for i in range(0, n, length):
            w = 1.0 + 0.0j
            for k in range(i, i + half):
                u = a[k]
                v = a[k + half] * w
                a[k] = u + v
                a[k + half] = u - v
                w *= wl
        length <<= 1
    if invert:
        for i in range(n):
            a[i] /= n
    return a


def ifft2(grid):
    n = len(grid)
    rows = [fft(list(row), invert=True) for row in grid]
    cols = [fft([rows[r][c] for r in range(n)], invert=True) for c in range(n)]
    return [[cols[c][r] for c in range(n)] for r in range(n)]


def wavenumber(index, n, patch):
    m = index if index < n // 2 else index - n
    return 2.0 * math.pi * m / patch


def spectrum():
    rng = random.Random(SEED)
    big_l = WIND_MS * WIND_MS / G
    small_l = big_l / 1000.0
    k_max = 2.0 * math.pi / (MIN_TEXELS_PER_WAVE * PATCH_M / SIZE)
    sx = [[0j] * SIZE for _ in range(SIZE)]
    sy = [[0j] * SIZE for _ in range(SIZE)]
    for r in range(SIZE):
        kv = wavenumber(r, SIZE, PATCH_M)
        for c in range(SIZE):
            ku = wavenumber(c, SIZE, PATCH_M)
            g1, g2 = rng.gauss(0.0, 1.0), rng.gauss(0.0, 1.0)
            k = math.hypot(ku, kv)
            if k < 1e-9 or k > k_max:
                continue
            cos_w = (ku * WIND_DIR[0] + kv * WIND_DIR[1]) / k
            phillips = math.exp(-1.0 / (k * big_l) ** 2) / k ** 4 * abs(cos_w) ** SPREAD_POWER
            phillips *= math.exp(-(k * small_l) ** 2)
            if cos_w < 0.0:
                phillips *= AGAINST_WIND
            h0 = complex(g1, g2) * math.sqrt(phillips / 2.0)
            sx[r][c] = 1j * ku * h0
            sy[r][c] = 1j * kv * h0
    return sx, sy


def png_rgb(width, height, rows):
    raw = b"".join(b"\x00" + bytes(row) for row in rows)

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parents[1] / "assets" / "terrain_detail" / "ocean")
    args = parser.parse_args(argv)
    fx, fy = spectrum()
    slope_u = [[v.real for v in row] for row in ifft2(fx)]
    slope_v = [[v.real for v in row] for row in ifft2(fy)]   # v = image rows, downward
    n = SIZE * SIZE
    var_u = sum(v * v for row in slope_u for v in row) / n
    var_v = sum(v * v for row in slope_v for v in row) / n
    rms = math.sqrt(var_u + var_v)
    gain = TARGET_RMS_ENCODED / rms
    rows = []
    for r in range(SIZE):
        row = []
        for c in range(SIZE):
            # The surface normal of z = h(u, v): (-dh/du, -dh/dv, 1). OpenGL
            # green is the component toward image-up, i.e. -v: +dh/dv.
            x = -gain * slope_u[r][c]
            y = gain * slope_v[r][c]
            z = 1.0
            inv = 1.0 / math.sqrt(x * x + y * y + z * z)
            row.extend(max(0, min(255, int(round((comp * inv * 0.5 + 0.5) * 255.0))))
                       for comp in (x, y, z))
        rows.append(row)
    args.out.mkdir(parents=True, exist_ok=True)
    png = png_rgb(SIZE, SIZE, rows)
    (args.out / "ocean_normal_512.png").write_bytes(png)
    meta = {
        "format": "flightsim.ocean_normal", "version": 1,
        "generator": "scripts/make_ocean_normal.py (Phillips spectrum, Tessendorf 2001)",
        "licence": "CC0-1.0 (this project's own output)",
        "size": SIZE, "patch_m": PATCH_M, "wind_ms": WIND_MS, "wind_dir": list(WIND_DIR),
        "seed": SEED, "against_wind": AGAINST_WIND, "min_texels_per_wave": MIN_TEXELS_PER_WAVE,
        "convention": "OpenGL (green = slope toward image-up), RGB = n * 0.5 + 0.5",
        "spread_power": SPREAD_POWER,
        "encoded_slope_rms": TARGET_RMS_ENCODED,
        "encoded_slope_rms_basis": "the slope field normalised to this RMS (the spectrum's amplitude is arbitrary)",
        "png_sha256": hashlib.sha256(png).hexdigest(),
        "pixels_sha256": hashlib.sha256(b"".join(bytes(row) for row in rows)).hexdigest(),
    }
    (args.out / "ocean_normal.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
