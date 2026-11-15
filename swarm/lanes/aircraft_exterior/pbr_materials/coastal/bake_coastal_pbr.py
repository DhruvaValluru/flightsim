"""Offline bake (Mac) of the coastal aircraft-exterior PBR weathering set.

VISUAL-ONLY. Nothing here touches a -quality=measure render or a label.

What it writes, per tier, under ``--out`` (default ``baked/`` beside this file):

* ``T_AcCoastal_DetailN_<size>.png`` -- tileable tangent-space detail normal,
  DirectX / UE convention (green points DOWN the image). Skin oil-canning
  (shallow pillowing between frames and stringers) plus paint orange-peel.
  Import as TC_Normalmap (BC5, two channels, Z rebuilt in the shader).
* ``T_AcCoastal_Mask_<size>.png`` -- tileable packed LINEAR mask.
  R = salt-film deposit, G = roughness breakup (0.5 = none),
  B = flow-aligned grime streaks (the flow runs along +U).
  Import as TC_Masks, sRGB OFF (BC1 at tiers 0-1, BC7 at tiers 2-3).
* ``coastal_pbr_manifest.json`` -- the tier table, every material parameter,
  each file's sha256, and the albedo bounds the test checks.

The render path only SAMPLES these (2 texture reads at tier 0); the noise the
laptop cannot afford per pixel is done here, once.

Everything is deterministic for a given numpy build (seeded PCG64 + FFT).
The shipped PNGs are the Mac's bake; do not re-bake on the laptop.

    .venv/bin/python swarm/lanes/aircraft_exterior/pbr_materials/coastal/bake_coastal_pbr.py --tiers 0
    .venv/bin/python swarm/lanes/aircraft_exterior/pbr_materials/coastal/bake_coastal_pbr.py --tiers 0,1,2,3 --out /some/dir
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
sys.path.insert(0, str(REPO / "scripts"))
import physically_based as _pb  # noqa: E402  (vendored CC0 database, sha256-pinned)

SCHEMA = "flightsim-swarm-aircraft-coastal-pbr/1"
UNCALIBRATED = "UNCALIBRATED: look choice, set by probe render on the Windows laptop"

# ---- tiers ---------------------------------------------------------------
#: bits per pixel of the block formats the importer is asked for.
BPP = {"BC1": 4, "BC5": 8, "BC7": 8}
MIP_CHAIN = 4.0 / 3.0
TIERS = {
    0: {"normal_px": 512, "mask_px": 512, "mask_format": "BC1", "samples": 2,
        "projection": "UV0 x tiling", "aniso": 2,
        "summary": "512 px BC5 detail normal + 512 px BC1 salt/roughness/grime mask, "
                   "2 texture reads on UV0, no extra passes"},
    1: {"normal_px": 1024, "mask_px": 1024, "mask_format": "BC1", "samples": 2,
        "projection": "UV0 x tiling", "aniso": 4,
        "summary": "1024 px versions of tier 0, same 2 reads, detail normal faded by distance"},
    2: {"normal_px": 2048, "mask_px": 2048, "mask_format": "BC7", "samples": 4,
        "projection": "UV0 x tiling, two scales", "aniso": 4,
        "summary": "2048 px, BC7 mask, each map read at two scales (4 reads) to hide tiling"},
    3: {"normal_px": 4096, "mask_px": 2048, "mask_format": "BC7", "samples": 6,
        "projection": "object-space two-plane", "aniso": 8,
        "summary": "4096 px normal, object-space two-plane projection (6 reads), 8x anisotropy"},
}


def est_vram_mb(tier: int) -> float:
    """ESTIMATE: compressed size with a full mip chain. Not measured."""
    t = TIERS[tier]
    bits = t["normal_px"] ** 2 * BPP["BC5"] + t["mask_px"] ** 2 * BPP[t["mask_format"]]
    return round(bits / 8 * MIP_CHAIN / 2 ** 20, 2)


# ---- material parameters ---------------------------------------------------
SALT_ALBEDO = _pb.linear_color(_pb.material("Salt"))
TIRE_ALBEDO = _pb.linear_color(_pb.material("Tire"))

#: The calibrated albedo range for the painted exterior (linear sRGB).
#: Floor: the database's measured tyre rubber, the darkest material on an
#: airframe (nothing painted is darker). Ceiling: scripts/aircraft_look.py
#: CLASS_SCALARS["paint"]["AlbedoMax"] (0.9, that file's own figure).
ALBEDO_MIN = round(max(TIRE_ALBEDO), 4)
ALBEDO_MAX = 0.9

#: New scalars the coastal weathering block reads. Every one is a look choice.
COASTAL_SCALARS = {
    "CoastalWeathering": 1.0,     # 0 = the block is a no-op (the reference frame)
    "DetailTiling": 6.0,          # tiles of the detail maps per UV0 unit
    "DetailNormalAmount": 0.6,    # 0 = vertex normal
    "SaltAmount": 0.5,            # scales mask R
    "SaltAlbedoWeight": 0.05,     # max lerp of base colour toward measured salt
    "SaltRoughness": 0.25,        # roughness added where the film is full
    "SaltCoatRoughness": 0.12,    # clear-coat roughness added (film hazes the gloss)
    "GrimeDarkening": 0.5,        # albedo lost where grime x GrimeAmount is 1
    "GrimeRoughness": 0.15,
    "RoughnessMin": 0.08,         # low sun: keeps the glint wider than a pixel
    "AlbedoMin": ALBEDO_MIN,
    "DetailFadeStartCm": 3000.0,  # tiers 1+: detail normal fades out by distance
    "DetailFadeEndCm": 12000.0,
}
#: Overrides of existing paint / bare-metal scalars for this scenario.
CLASS_OVERRIDES = {
    "paint": {"GrimeAmount": 0.2, "PanelDarkening": 0.12, "ClearCoatRoughness": 0.1},
    "bare_metal": {"GrimeAmount": 0.2, "PanelDarkening": 0.12},
}
#: The gate this lane must not break (docs: no dark-aircraft regression).
MAX_TEXEL_DARKENING = 0.15   # no texel loses more than 15 % of its albedo
MEAN_ALBEDO_BAND = (0.97, 1.08)  # mean albedo after / before, 18 % grey base


def weather(base, mask_r, mask_g, mask_b, roughness=0.4, roughness_breakup=0.12,
            grime_amount=0.2, coat_roughness=0.1, p=COASTAL_SCALARS):
    """Python twin of coastal_weathering.ush. Arrays or floats in, the
    weathered (albedo, roughness, clear-coat roughness) out. ``base`` is a
    scalar or (..., 3) linear albedo."""
    base = np.asarray(base, dtype=np.float64)
    k = p["CoastalWeathering"]
    salt = np.asarray(mask_r) * p["SaltAmount"] * k
    grime = np.asarray(mask_b) * grime_amount * k
    if base.ndim:
        salt_c, grime_c, target = salt[..., None], grime[..., None], np.asarray(SALT_ALBEDO)
    else:
        salt_c, grime_c, target = salt, grime, float(np.mean(SALT_ALBEDO))
    albedo = base * (1.0 - p["GrimeDarkening"] * grime_c)
    albedo = albedo + (target - albedo) * p["SaltAlbedoWeight"] * salt_c
    albedo = np.clip(albedo, p["AlbedoMin"], ALBEDO_MAX)
    rough = (roughness + roughness_breakup * (np.asarray(mask_g) - 0.5) * 2.0 * k
             + p["SaltRoughness"] * salt + p["GrimeRoughness"] * grime)
    rough = np.clip(rough, p["RoughnessMin"], 1.0)
    coat = np.clip(coat_roughness + p["SaltCoatRoughness"] * salt, 0.0, 1.0)
    return albedo, rough, coat


# ---- tileable noise ----------------------------------------------------------
def band_noise(n, rng, centre, width, stretch_u=1.0):
    """Tileable noise: white noise band-passed in the frequency domain
    (cycles per tile). ``stretch_u`` > 1 smears along U (image columns): the
    uniform-flow limit of a line integral convolution. Returned zero-mean,
    unit standard deviation."""
    fy = np.fft.fftfreq(n, 1.0 / n)[:, None]
    fx = np.fft.fftfreq(n, 1.0 / n)[None, :] * stretch_u
    radius = np.sqrt(fx * fx + fy * fy)
    gain = np.exp(-0.5 * ((radius - centre) / width) ** 2)
    gain[0, 0] = 0.0
    field = np.fft.ifft2(np.fft.fft2(rng.standard_normal((n, n))) * gain).real
    return field / field.std()


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def bake_height(n, seed=20261112, bays=(8, 4)):
    """Tileable height (arbitrary units, bay-pillow amplitude ~1): oil-canning
    pillows on a bays[0] x bays[1] grid of skin bays plus fine orange-peel."""
    rng = np.random.default_rng(seed)
    bu, bv = bays
    v, u = np.meshgrid(np.arange(n) / n, np.arange(n) / n, indexing="ij")
    cu, cv = u * bu, v * bv
    amp = rng.uniform(-1.0, 0.35, size=(bv, bu))  # mostly inward (suction side dishes)
    bay = amp[np.floor(cv).astype(int) % bv, np.floor(cu).astype(int) % bu]
    pillow = (np.sin(np.pi * (cu % 1.0)) * np.sin(np.pi * (cv % 1.0))) ** 1.5
    return bay * pillow + 0.02 * band_noise(n, rng, centre=n / 6.0, width=n / 16.0)


def height_to_normal(height, slope=0.05):
    """DirectX-convention tangent normal (uint8 RGB) of a tileable height.
    ``slope`` is the tangent of the steepest tilt a unit height step per
    bay would give; the result is in texel-independent units."""
    n = height.shape[0]
    scale = slope * n / 8.0
    d_col = (np.roll(height, -1, 1) - np.roll(height, 1, 1)) * 0.5 * scale
    d_row = (np.roll(height, -1, 0) - np.roll(height, 1, 0)) * 0.5 * scale
    nx, ny, nz = -d_col, -d_row, np.ones_like(height)  # green down: -dH/drow
    inv = 1.0 / np.sqrt(nx * nx + ny * ny + nz * nz)
    rgb = np.stack([nx * inv, ny * inv, nz * inv], -1) * 0.5 + 0.5
    return np.round(rgb * 255.0).astype(np.uint8)


def bake_mask(n, seed=20261113):
    """uint8 RGB packed mask (linear): salt, roughness breakup, grime streaks."""
    rng = np.random.default_rng(seed)
    blotch = band_noise(n, rng, centre=3.0, width=2.0)
    crystal = band_noise(n, rng, centre=n / 10.0, width=n / 20.0)
    salt = smoothstep(-0.6, 1.2, blotch) * (0.75 + 0.25 * smoothstep(-1.0, 1.0, crystal))
    breakup = np.clip(0.5 + 0.18 * band_noise(n, rng, centre=10.0, width=6.0), 0.0, 1.0)
    streak = band_noise(n, rng, centre=14.0, width=8.0, stretch_u=12.0)
    grime = smoothstep(0.5, 2.2, streak)
    rgb = np.stack([salt, breakup, grime], -1)
    return np.round(np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def albedo_report(mask_u8):
    """The numbers the dark-aircraft gate rests on, from the baked mask."""
    m = mask_u8.astype(np.float64) / 255.0
    out = {}
    for name, base in (("grey_card_0.18", 0.18), ("dark_livery_0.05", 0.05), ("white_0.9", 0.9)):
        albedo, _, _ = weather(base, m[..., 0], m[..., 1], m[..., 2])
        out[name] = {"mean_ratio": round(float(albedo.mean() / base), 4),
                     "min_ratio": round(float(albedo.min() / base), 4),
                     "min": round(float(albedo.min()), 4), "max": round(float(albedo.max()), 4)}
    return out


def bake(out_dir, tiers=(0,)):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": SCHEMA, "visual_only": True, "status": UNCALIBRATED,
        "normal_convention": "DirectX (green down), tangent space, UE TC_Normalmap",
        "mask_channels": {"R": "salt film", "G": "roughness breakup, 0.5 neutral",
                          "B": "grime streaks, flow along +U"},
        "albedo_range_linear": [ALBEDO_MIN, ALBEDO_MAX],
        "salt_albedo_linear": list(SALT_ALBEDO),
        "coastal_scalars": COASTAL_SCALARS, "class_overrides": CLASS_OVERRIDES,
        "gate": {"max_texel_darkening": MAX_TEXEL_DARKENING, "mean_albedo_band": list(MEAN_ALBEDO_BAND)},
        "tiers": {},
    }
    for tier in tiers:
        t = TIERS[tier]
        files = {}
        normal = height_to_normal(bake_height(t["normal_px"]))
        mask = bake_mask(t["mask_px"])
        for stem, array in ((f"T_AcCoastal_DetailN_{t['normal_px']}", normal),
                            (f"T_AcCoastal_Mask_{t['mask_px']}", mask)):
            path = out_dir / f"{stem}.png"
            Image.fromarray(array).save(path, optimize=True)
            files[path.name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        manifest["tiers"][str(tier)] = {
            **t, "normal_format": "BC5", "est_vram_mb": est_vram_mb(tier),
            "est_vram_is": "ESTIMATE (block size x 4/3 mip chain), not measured",
            "files": files, "albedo": albedo_report(mask)}
    (out_dir / "coastal_pbr_manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bake the coastal aircraft PBR weathering set (Mac, offline).")
    ap.add_argument("--tiers", default="0")
    ap.add_argument("--out", default=str(HERE / "baked"))
    args = ap.parse_args(argv)
    manifest = bake(args.out, tuple(int(t) for t in args.tiers.split(",")))
    for tier, row in manifest["tiers"].items():
        print(f"tier {tier}: est {row['est_vram_mb']} MB (ESTIMATE)  grey-card mean albedo ratio "
              f"{row['albedo']['grey_card_0.18']['mean_ratio']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
