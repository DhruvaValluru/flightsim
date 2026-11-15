"""Storm airframe PBR: the offline bake (Mac) and the storm look's numbers.

VISUAL-ONLY. Nothing here touches the flight model, the labels or the
measure path. UNRENDERED when written: the authoring Mac cannot run the
pinned Windows UE build, so every number below that says UNCALIBRATED is a
look choice waiting for the Windows pixel gate in INTEGRATION.md.

What it bakes (tiling, UV-independent: the masters project them from the
mesh's LOCAL position, as panel_lines.hlsl and aircraft_wet.hlsl already do,
so no airframe UV set and no placeholder airframe is needed):

* ``T_AcStorm_PanelN``  BC5 tangent slope (x NORMAL_ENCODE_GAIN), ONE panel cell per tile: the
  groove at the tile edge, the skin's oil-canning pillow inside it, a fine
  orange-peel, and (tier >= 1) a rivet row. Sampled at local / PanelPitchCm.
* ``T_AcStorm_Wet``     BC5 R = rivulet mask (V runs aft, scrolled by the
  existing TimeS x StreakSpeedPerKt x AirspeedKts), G = grime / roughness
  break-up (low frequency).
* ``T_AcStorm_Aux``     BC5 R = bead mask (gravity regime), G = groove
  occlusion (tier >= 1 only).

and ``storm_look.json``: the per-tier render description, the storm
overrides of scripts/aircraft_look.py CLASS_SCALARS and
scripts/aircraft_wet_layer.py WET_DEFAULTS, and the ALBEDO BUDGET that is
this lane's gate: the worst a storm may darken a painted panel.

    .venv/bin/python swarm/lanes/aircraft_exterior/pbr_materials/storm/bake_storm_pbr.py --tier 0

Deterministic: one seed, numpy's PCG64, no clock. numpy only (no PIL).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path

import numpy as np

LANE = Path(__file__).resolve().parent
SCHEMA = "flightsim-swarm-aircraft-storm-pbr/1"
SEED = 20261112
UNCALIBRATED = "UNCALIBRATED: set by probe render on the render machine"

# -- what the rest of the storm scenario must agree with ----------------------
#: Read from the shared code on 2026-11-12 and PINNED by the lane's test, so a
#: change there fails here by name instead of drifting.
SHARED = {
    "rain_rate_mmh": 40.0,               # core/scene/weather_look.py STORM_RAIN_MMH
    "wet_saturation_mmh": 4.0,           # scripts/aircraft_wet_layer.py WetSaturationMmh
    "airframe_wetness": 1.0,             # saturate(40 / 4)
    "exposure_meter_target_p90": 0.40,   # core/scene/beauty_look.py EXPOSURE_METER_TARGET_P90["storm"]
    "colour_temperature_k": 6100.0,      # beauty_look.py GRADES["storm"]["WhiteTemp"]
    "grade_saturation": 0.75,            # GRADES["storm"]["ColorSaturation"][3]
    "grade_contrast": 1.1,               # GRADES["storm"]["ColorContrast"][3]
    "ev100_offset": 0.0,                 # GRADES["storm"]["ev100_offset"]
    "dynamic_gi": "none (r.DynamicGlobalIlluminationMethod 0, D3D11 SM5)",
}

# -- the calibrated albedo range ----------------------------------------------
#: Dielectric base colour, sRGB 8-bit. 243 is the paint master's own AlbedoMax
#: (0.9 linear, scripts/aircraft_look.py). 50 is the usual PBR validation floor
#: for a non-metal (from memory: the Unity / Frostbite validation charts;
#: charcoal is about there). UNCALIBRATED as a pair.
ALBEDO_SRGB_RANGE = (50, 243)

#: HEAD's numbers this lane overrides (pinned to the shared files by the test).
HEAD = {"PorosityPaint": 0.3, "PorosityBareMetal": 0.12,
        "GrimeAmount": 0.2, "PanelDarkening": 0.15, "AlbedoMax": 0.9}

#: The storm overrides. Why: aircraft_wet.hlsl darkens by
#: lerp(a, a^2, wet x porosity). That is the porous-surface model (from memory:
#: Lekner and Dorf 1988, "Why some things are darker when wet"; Lagarde 2013,
#: "Physically based wet surfaces"). A painted panel under a clear coat is NOT
#: porous: water changes its gloss, hardly its diffuse colour. At wetness 1
#: (any rain over 4 mm/h, so always in the storm) HEAD's 0.3 takes a dark
#: livery (linear 0.05) down 28 % before grime and grooves, in a frame that
#: has no Lumen fill to lift it. All UNCALIBRATED.
STORM_OVERRIDES = {
    "wet": {"PorosityPaint": 0.05, "PorosityBareMetal": 0.0,
            "WetRoughness": 0.08, "WetCoatRoughness": 0.03},
    "paint": {"GrimeAmount": 0.10, "PanelDarkening": 0.10, "ClearCoat": 1.0,
              "AlbedoMin": 0.0319, "AlbedoMax": 0.9},
    "bare_metal": {"GrimeAmount": 0.20, "PanelDarkening": 0.10},
}

#: The gate. ``worst``: the darkest texel (full grime, in a groove, wet) keeps
#: at least this share of its dry, clean albedo. ``mean``: the same over the
#: baked masks' area means. ``vs_head``: never darker than HEAD's storm.
BUDGET = {"worst_min": 0.70, "mean_min": 0.90, "vs_head_min": 1.0}

#: The panel map stores slope x this (see normal_from_height).
NORMAL_ENCODE_GAIN = 8.0

TIERS = {
    0: {"size": 256, "textures": ("PanelN", "Wet"), "projection": "dominant-axis (1 tap per map)",
        "summary": "2 BC5 maps at 256, dominant-axis projection, 2 taps; replaces the procedural "
                   "panel_lines and rivulet noise; beads and groove AO off; clear coat stays."},
    1: {"size": 512, "textures": ("PanelN", "Wet", "Aux"), "projection": "dominant-axis (1 tap per map)",
        "summary": "3 BC5 maps at 512, 3 taps; adds beads, rivets and groove AO."},
    2: {"size": 1024, "textures": ("PanelN", "Wet", "Aux"), "projection": "triplanar (3 taps per map)",
        "summary": "3 BC5 maps at 1024, triplanar (9 taps): no projection stretch on curved skin."},
    3: {"size": 2048, "textures": ("PanelN", "Wet", "Aux"), "projection": "triplanar (3 taps per map)",
        "summary": "3 BC5 maps at 2048, triplanar, 16x anisotropic; stress-ladder only."},
}


def srgb_to_linear(v8: float) -> float:
    c = v8 / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def vram_mb(tier: int) -> float:
    """ESTIMATE: BC5 is 1 byte per texel, a full mip chain adds a third."""
    t = TIERS[tier]
    return round(len(t["textures"]) * t["size"] ** 2 * 4.0 / 3.0 / 2 ** 20, 2)


# -- the albedo model (aircraft_wet.hlsl line 126 and the wear multipliers) ----
def effective_albedo(albedo, porosity, grime_amount, panel_darkening, grime=1.0, groove=1.0,
                     wetness=1.0, albedo_min=0.0, albedo_max=1.0):
    """Linear diffuse albedo after grime, groove darkening and the wet film.

    A MODEL of the master graph (multiplicative grime and groove, then the
    film), deliberately the pessimistic order. ``grime`` and ``groove`` are the
    mask values (1 = full)."""
    a = np.clip(np.asarray(albedo, dtype=float), albedo_min, albedo_max)
    a = a * (1.0 - grime_amount * grime) * (1.0 - panel_darkening * groove)
    k = wetness * porosity
    return a * (1.0 - k) + a * a * k


def albedo_budget(grime_mean=0.5, groove_mean=0.1):
    lo, hi = (srgb_to_linear(v) for v in ALBEDO_SRGB_RANGE)
    a = np.linspace(lo, hi, 64)
    paint, wet = STORM_OVERRIDES["paint"], STORM_OVERRIDES["wet"]

    def storm(g, p):
        return effective_albedo(a, wet["PorosityPaint"], paint["GrimeAmount"], paint["PanelDarkening"],
                                g, p, albedo_min=paint["AlbedoMin"], albedo_max=paint["AlbedoMax"])

    def head(g, p):
        return effective_albedo(a, HEAD["PorosityPaint"], HEAD["GrimeAmount"], HEAD["PanelDarkening"],
                                g, p, albedo_max=HEAD["AlbedoMax"])

    out = {
        "albedo_linear_range": [round(lo, 4), round(hi, 4)],
        "worst_ratio": float((storm(1, 1) / a).min()),
        "mean_ratio": float((storm(grime_mean, groove_mean) / a).min()),
        "vs_head_worst": float((storm(1, 1) / head(1, 1)).min()),
        "vs_head_mean": float((storm(grime_mean, groove_mean) / head(grime_mean, groove_mean)).min()),
        "head_worst_ratio": float((head(1, 1) / a).min()),
        "mask_means": {"grime": grime_mean, "groove": groove_mean},
        "limits": BUDGET,
    }
    out["pass"] = bool(out["worst_ratio"] >= BUDGET["worst_min"] and out["mean_ratio"] >= BUDGET["mean_min"]
                       and out["vs_head_worst"] >= BUDGET["vs_head_min"])
    return out


# -- tiling fields -------------------------------------------------------------
def _fft_noise(rng, n, sigma_u, sigma_v):
    """Periodic Gaussian-filtered white noise in 0..1 (sigmas in texels)."""
    f = np.fft.fft2(rng.standard_normal((n, n)))
    ku = np.fft.fftfreq(n)[None, :]
    kv = np.fft.fftfreq(n)[:, None]
    f *= np.exp(-2.0 * np.pi ** 2 * ((ku * sigma_u) ** 2 + (kv * sigma_v) ** 2))
    x = np.fft.ifft2(f).real
    x -= x.min()
    return x / max(x.max(), 1e-12)


def _smooth(x, lo, hi):
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def panel_fields(n, tier, rng):
    """(height, groove) for one panel cell per tile. Height in tile units."""
    u = (np.arange(n) + 0.5) / n
    uu, vv = np.meshgrid(u, u)
    edge = np.minimum(np.minimum(uu, 1 - uu), np.minimum(vv, 1 - vv))     # 0 at the seam
    groove = 1.0 - _smooth(edge, 0.0, 0.012)
    pillow = np.sin(np.pi * uu) ** 2 * np.sin(np.pi * vv) ** 2            # oil-canning
    peel = _fft_noise(rng, n, n / 96.0, n / 96.0) - 0.5
    warp = _fft_noise(rng, n, n / 6.0, n / 6.0) - 0.5
    height = 0.004 * pillow + 0.002 * warp + 0.00012 * peel - 0.0018 * groove
    if tier >= 1:                                                         # a rivet row inside each seam
        pitch = 1.0 / 24.0
        along = np.minimum(np.abs((uu / pitch) % 1 - 0.5), np.abs((vv / pitch) % 1 - 0.5)) * pitch
        ring = np.abs(edge - 0.035)
        rivet = 1.0 - _smooth(np.hypot(ring, along), 0.0, 0.006)
        height = height + 0.0006 * rivet
    return height, groove


def normal_from_height(height):
    """Slope XY in 0..1, DirectX / UE convention (green = -dH/dv).

    Stored as clip(NORMAL_ENCODE_GAIN x slope, -1, 1): a skin's real slopes are
    under one 8-bit step, so the map spends its range on them and the master
    divides the gain back out (INTEGRATION.md: n = normalize(-sx, -sy, 1))."""
    n = height.shape[0]
    dx = (np.roll(height, -1, 1) - np.roll(height, 1, 1)) * n / 2.0
    dy = (np.roll(height, -1, 0) - np.roll(height, 1, 0)) * n / 2.0
    g = NORMAL_ENCODE_GAIN
    return np.stack([np.clip(-dx * g, -1, 1) * 0.5 + 0.5, np.clip(dy * g, -1, 1) * 0.5 + 0.5], axis=-1)


def wet_fields(n, rng):
    """(rivulet, grime, bead), each 0..1 and tiling."""
    riv = _fft_noise(rng, n, n / 300.0, n / 7.0)                          # long aft, thin across
    riv = _smooth(riv, 0.60, 0.74)
    grime = _fft_noise(rng, n, n / 10.0, n / 5.0)
    grime = (grime - grime.mean()) * 1.6 + 0.5                            # area mean 0.5 by construction
    bead = _smooth(_fft_noise(rng, n, n / 140.0, n / 140.0), 0.66, 0.74)
    return riv, np.clip(grime, 0.0, 1.0), bead


# -- BC5 / DDS / PNG -----------------------------------------------------------
def _bc4_blocks(ch8):
    """BC4 (8-value mode) of an (h, w) uint8 image, h and w multiples of 4."""
    h, w = ch8.shape
    b = ch8.reshape(h // 4, 4, w // 4, 4).transpose(0, 2, 1, 3).reshape(-1, 16).astype(np.int32)
    a0, a1 = b.max(1), b.min(1)
    flat = a0 == a1
    a0 = np.where(flat & (a0 < 255), a0 + 1, a0)                          # keep a0 > a1: 8-value mode
    a1 = np.where(flat & (a1 == 255), 254, a1)
    w8 = np.arange(1, 7)
    pal = np.concatenate([a0[:, None], a1[:, None],
                          ((7 - w8)[None, :] * a0[:, None] + w8[None, :] * a1[:, None]) // 7], axis=1)
    idx = np.abs(b[:, :, None] - pal[:, None, :]).argmin(2).astype(np.uint64)
    bits = (idx << (3 * np.arange(16, dtype=np.uint64))[None, :]).sum(1, dtype=np.uint64)
    out = np.empty((b.shape[0], 8), dtype=np.uint8)
    out[:, 0], out[:, 1] = a0, a1
    for i in range(6):
        out[:, 2 + i] = (bits >> np.uint64(8 * i)) & np.uint64(0xFF)
    return out


def bc4_decode(blocks, h, w):
    """The decoder the test round-trips through."""
    a0, a1 = blocks[:, 0].astype(np.int32), blocks[:, 1].astype(np.int32)
    w8 = np.arange(1, 7)
    pal = np.concatenate([a0[:, None], a1[:, None],
                          ((7 - w8)[None, :] * a0[:, None] + w8[None, :] * a1[:, None]) // 7], axis=1)
    bits = sum(blocks[:, 2 + i].astype(np.uint64) << np.uint64(8 * i) for i in range(6))
    idx = ((bits[:, None] >> (3 * np.arange(16, dtype=np.uint64))[None, :]) & np.uint64(7)).astype(np.int64)
    px = np.take_along_axis(pal, idx, 1)
    return px.reshape(h // 4, w // 4, 4, 4).transpose(0, 2, 1, 3).reshape(h, w).astype(np.uint8)


def _mips(img):
    """Box-filtered chain down to 1x1 (float image, (n, n, c), n a power of 2)."""
    chain = [img]
    while chain[-1].shape[0] > 1:
        a = chain[-1]
        chain.append((a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2]) / 4.0)
    return chain


def to_u8(x):
    return np.clip(np.rint(x * 255.0), 0, 255).astype(np.uint8)


def dds_bc5(rg):
    """A legacy-FourCC ``ATI2`` (BC5 unsigned) DDS with a full mip chain."""
    n = rg.shape[0]
    chain = _mips(rg.astype(float))
    body = bytearray()
    for m in chain:
        m8 = to_u8(m)
        if m8.shape[0] < 4:                                               # tiling, so repeat to one block
            reps = 4 // m8.shape[0]
            m8 = np.tile(m8, (reps, reps, 1))
        body += np.concatenate([_bc4_blocks(m8[..., 0]), _bc4_blocks(m8[..., 1])], axis=1).tobytes()
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000                  # caps h w pixfmt mips linearsize
    header = struct.pack("<4s7I44x", b"DDS ", 124, flags, n, n, max(1, n // 4) ** 2 * 16, 0, len(chain))
    header += struct.pack("<2I4s5I", 32, 0x4, b"ATI2", 0, 0, 0, 0, 0)     # DDPF_FOURCC
    header += struct.pack("<4I4x", 0x1000 | 0x8 | 0x400000, 0, 0, 0)      # texture | complex | mipmap
    assert len(header) == 128
    return bytes(header) + bytes(body)


def png_rgb(rgb8):
    """A plain 8-bit RGB PNG (the importer's fallback and the reader's view)."""
    h, w, _ = rgb8.shape
    raw = b"".join(b"\x00" + rgb8[y].tobytes() for y in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# -- the bake ------------------------------------------------------------------
def bake_maps(tier):
    """{name: (n, n, 2) float RG in 0..1} for a tier, plus the mask means."""
    t = TIERS[tier]
    n = t["size"]
    rng = np.random.Generator(np.random.PCG64(SEED))                      # same fields at every tier
    height, groove = panel_fields(n, tier, rng)
    riv, grime, bead = wet_fields(n, rng)
    maps = {"PanelN": normal_from_height(height), "Wet": np.stack([riv, grime], -1)}
    if "Aux" in t["textures"]:
        maps["Aux"] = np.stack([bead, 1.0 - 0.6 * groove], -1)            # G: occlusion, 1 = open
    means = {"grime": float(grime.mean()), "groove": float(groove.mean()),
             "rivulet": float(riv.mean()), "bead": float(bead.mean())}
    return maps, means


def bake(tier, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    maps, means = bake_maps(tier)
    files = {}
    for name, rg in maps.items():
        blue = np.ones(rg.shape[:2] + (1,)) if name == "PanelN" else np.zeros(rg.shape[:2] + (1,))
        for ext, data in (("dds", dds_bc5(rg)), ("png", png_rgb(to_u8(np.concatenate([rg, blue], -1))))):
            path = out_dir / f"T_AcStorm_{name}.{ext}"
            path.write_bytes(data)
            files[path.name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    t = TIERS[tier]
    look = {
        "schema": SCHEMA, "visual_only": True, "status": UNCALIBRATED, "seed": SEED, "tier": tier,
        "size": t["size"], "projection": t["projection"], "summary": t["summary"],
        "est_vram_mb": vram_mb(tier), "est_vram_note": "ESTIMATE: BC5 1 byte/texel x 4/3 mips; not measured",
        "textures": {
            "T_AcStorm_PanelN": {"format": "BC5 (ATI2), linear, TC_Masks or TC_BC5 (NOT TC_Normalmap: slopes are gain-encoded)", "uv": "local / PanelPitchCm",
                                 "channels": "RG = slope XY x NormalEncodeGain, DirectX (UE) green",
                                 "NormalEncodeGain": NORMAL_ENCODE_GAIN},
            "T_AcStorm_Wet": {"format": "BC5 (ATI2), linear, TC_Masks", "uv": "local / (StreakPitchCm x 24), "
                              "V scrolled aft by TimeS x StreakSpeedPerKt x AirspeedKts",
                              "channels": "R = rivulet, G = grime / roughness break-up"},
            **({"T_AcStorm_Aux": {"format": "BC5 (ATI2), linear, TC_Masks", "uv": "R: as Wet, unscrolled; "
                                  "G: as PanelN", "channels": "R = bead, G = groove occlusion (1 = open)"}}
               if "Aux" in maps else {}),
        },
        "files": files, "mask_means": means,
        "overrides": STORM_OVERRIDES, "head": HEAD, "shared": SHARED,
        "albedo_srgb_range": list(ALBEDO_SRGB_RANGE),
        "albedo_budget": albedo_budget(means["grime"], means["groove"]),
    }
    (out_dir / "storm_look.json").write_text(json.dumps(look, indent=2, sort_keys=True) + "\n")
    return look


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tier", type=int, choices=sorted(TIERS), default=0)
    ap.add_argument("--out", default=None, help="default: <lane>/baked/tier<N>")
    args = ap.parse_args(argv)
    out = Path(args.out) if args.out else LANE / "baked" / f"tier{args.tier}"
    look = bake(args.tier, out)
    b = look["albedo_budget"]
    print(f"tier {args.tier}: {len(look['files'])} files in {out}, est {look['est_vram_mb']} MB (ESTIMATE)")
    print(f"albedo budget: worst {b['worst_ratio']:.3f} mean {b['mean_ratio']:.3f} "
          f"vs HEAD {b['vs_head_worst']:.3f} (HEAD worst {b['head_worst_ratio']:.3f}) pass={b['pass']}")
    return 0 if b["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
