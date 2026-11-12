"""Offline bake for the aircraft canopy glass, scenario "coastal" (visual-only).

Runs on the Mac. Writes small textures the laptop only samples, so the glass
slot needs no Lumen, no ray tracing and (at tier 0) no translucency pass and
no screen-space reflections:

  T_GlassFresnel_LUT.png   64x1, linear. Indexed by N.V.
                           R = sqrt(two-face slab reflectance), unpolarised, incoherent
                           G = sqrt(single-face Fresnel reflectance)
                           B = slab transmittance incl. tint absorption along the
                               refracted path
  T_GlassEnv_<W>.png       lat-long strip of the coastal low-sun sky and sea the
                           canopy mirrors, sRGB-encoded, sun disc left OUT (the
                           directional light's specular lobe draws it). An
                           ANALYTIC stand-in, not a capture: see ENV_NOTE.
  T_GlassMicro_N_<S>.png   tileable tangent normal, RG = xy (green down, the
                           DirectX/UE convention), B = z. Polishing scratches
                           and crazing.
  T_GlassFilm_M_<S>.png    tileable, linear. R = roughness add, G = salt-film
                           coverage, B = scratch mask (sun-glint streak weight).
  glass_coastal.json       every number above plus tiers, sha256 and the
                           predicted canopy luma used by the source test.

  python bake_glass.py bake [--out DIR]
  python bake_glass.py measure --ref REF.png --cand CAND.png \
        --canopy-roi x0,y0,x1,y1 --aircraft-roi x0,y0,x1,y1

`measure` is the pixel gate; it only counts when run on frames rendered on the
Windows laptop. Nothing here is a measured visual result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SEED = 20261112

# -- look parameters (shared with the other coastal lanes) ---------------------
# Stated assumptions of this bake, not measurements.
SHARED = {
    "scenario": "coastal",
    "sun_elevation_deg": 12.0,
    "sun_azimuth_rel_deg": 0.0,          # env strip u=0.5 faces the sun
    "colour_temperature_k": 4300,        # low sun through sea haze (stated)
    "haze_scale_height_rad": 0.22,       # horizon haze falloff in elevation
    "haze_horizon_linear_rgb": [0.74, 0.70, 0.62],
    "sky_zenith_linear_rgb": [0.10, 0.19, 0.42],
    "sun_glow_linear_rgb": [0.55, 0.38, 0.20],
    "sun_glow_width_rad": 0.38,
    "sea_albedo": 0.06,
    "sea_tint_linear_rgb": [0.035, 0.065, 0.075],
    "water_ior": 1.333,
    "env_encode_scale": 1.5,             # linear radiance = decode_srgb(png) * scale
}
ENV_NOTE = ("Analytic gradient sky + Fresnel sea, visual-only. Replace with the sky "
            "lane's baked LUT when one exists; the integrator must keep SHARED in "
            "step with that lane or the canopy reflects a different sky than the "
            "one drawn behind it.")

# -- glass (matches scripts/aircraft_look.py, which this lane does not edit) ----
GLASS_IOR = 1.49                          # acrylic (PMMA) canopy, as aircraft_look.GLASS_IOR
GLASS_TINT_LINEAR = (0.018, 0.022, 0.026)  # aircraft_look GlassTint, unchanged
THIN_TRANSMITTANCE = (0.80, 0.84, 0.82)    # aircraft_look THIN_VECTORS, unchanged
SALT_FILM_ALBEDO = 0.75                    # dried sea-salt film, stated
SALT_FILM_MAX_COVERAGE = 0.12
ROUGHNESS_BASE = 0.02                      # aircraft_look thin roughness
ROUGHNESS_ADD_MAX = 0.10
ALBEDO_RANGE = (0.015, 0.90)               # stated bound for a dielectric base colour

LUT_W = 64

# tier -> what the render path samples. VRAM figures are ESTIMATES (texture
# bytes with a full mip chain); none of these tiers has been run on the laptop.
TIERS = {
    0: {"env_w": 64, "micro": 0, "blend": "opaque",
        "summary": "Opaque M_AircraftGlass + Fresnel LUT + 64x32 baked env strip; "
                   "no translucency, no SSR, no micro normal"},
    1: {"env_w": 128, "micro": 256, "blend": "opaque",
        "summary": "Tier 0 + 256 tiled micro-scratch normal and salt-film mask, 128x64 env"},
    2: {"env_w": 128, "micro": 512, "blend": "thin_translucent",
        "summary": "Thin Translucent MI_<slot>_thin (unlabelled frames) + LUT + env + 512 micro; SSR off"},
    3: {"env_w": 256, "micro": 1024, "blend": "thin_translucent",
        "summary": "Tier 2 at 1024 micro and 256x128 env, SSR on for the canopy"},
}


# -- optics --------------------------------------------------------------------
def fresnel_unpolarised(cos_i, n):
    """Exact Fresnel power reflectance, air -> dielectric n. Returns (Rs, Rp)."""
    cos_i = np.clip(np.asarray(cos_i, dtype=np.float64), 0.0, 1.0)
    sin_t2 = (1.0 - cos_i ** 2) / (n * n)
    cos_t = np.sqrt(np.clip(1.0 - sin_t2, 0.0, 1.0))
    rs = ((cos_i - n * cos_t) / (cos_i + n * cos_t + 1e-12)) ** 2
    rp = ((n * cos_i - cos_t) / (n * cos_i + cos_t + 1e-12)) ** 2
    return rs, rp


def slab_terms(cos_i, n=GLASS_IOR, internal_t=THIN_TRANSMITTANCE[1]):
    """(slab reflectance, single-face reflectance, slab transmittance).

    Two parallel faces, incoherent multiple bounces, per polarisation:
    R = r + (1-r)^2 r t^2 / (1 - r^2 t^2),  T = (1-r)^2 t / (1 - r^2 t^2)
    with t = internal_t ** (1 / cos_t): tint absorption along the refracted path.
    """
    cos_i = np.clip(np.asarray(cos_i, dtype=np.float64), 0.0, 1.0)
    cos_t = np.sqrt(np.clip(1.0 - (1.0 - cos_i ** 2) / (n * n), 1e-6, 1.0))
    t = internal_t ** (1.0 / cos_t)
    out_r, out_t = 0.0, 0.0
    pol = fresnel_unpolarised(cos_i, n)
    for r in pol:
        den = 1.0 - (r * t) ** 2
        out_r = out_r + 0.5 * (r + (1.0 - r) ** 2 * r * t * t / den)
        out_t = out_t + 0.5 * ((1.0 - r) ** 2 * t / den)
    single = 0.5 * (pol[0] + pol[1])
    return out_r, single, out_t


def srgb_encode(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def srgb_decode(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, np.power((x + 0.055) / 1.055, 2.4))


def luma(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


# -- bakes ---------------------------------------------------------------------
def bake_fresnel_lut(width=LUT_W):
    cos_i = (np.arange(width) + 0.5) / width
    r, single, t = slab_terms(cos_i)
    # R and G are stored as sqrt (the shader squares them): 8 bits linear would
    # leave only ~10 codes for the face-on 0.039.
    return np.stack([np.sqrt(r), np.sqrt(single), t], axis=-1)[None, :, :]   # (1, W, 3)


def sky_radiance(elev, dazim, p=SHARED):
    """Linear RGB of the sky dome (elev >= 0), sun disc excluded."""
    zen = np.array(p["sky_zenith_linear_rgb"])
    hor = np.array(p["haze_horizon_linear_rgb"])
    glow = np.array(p["sun_glow_linear_rgb"])
    k = np.exp(-np.clip(elev, 0, None) / p["haze_scale_height_rad"])[..., None]
    base = zen * (1.0 - k) + hor * k
    se = math.radians(p["sun_elevation_deg"])
    cosang = (np.sin(elev) * math.sin(se) + np.cos(elev) * math.cos(se) * np.cos(dazim))
    ang = np.arccos(np.clip(cosang, -1.0, 1.0))
    return base + glow * np.exp(-ang / p["sun_glow_width_rad"])[..., None]


def bake_env(width, p=SHARED):
    """Lat-long (W, W/2) linear radiance: sky above, Fresnel sea below."""
    h = width // 2
    v = (np.arange(h) + 0.5) / h
    u = (np.arange(width) + 0.5) / width
    elev = (0.5 - v)[:, None] * math.pi * np.ones((1, width))
    dazim = (u - 0.5)[None, :] * 2.0 * math.pi * np.ones((h, 1))
    up = sky_radiance(np.abs(elev), dazim, p)
    rs, rp = fresnel_unpolarised(np.sin(np.abs(elev)), p["water_ior"])
    f = (0.5 * (rs + rp))[..., None]
    sea = up * f + np.array(p["sea_tint_linear_rgb"]) * (1.0 - f)
    # sea haze swallows the far water into the horizon colour
    kh = np.exp(-np.abs(elev) / (0.35 * p["haze_scale_height_rad"]))[..., None]
    sea = sea * (1.0 - kh) + np.array(p["haze_horizon_linear_rgb"]) * kh
    return np.where((elev >= 0)[..., None], up, sea)


def _periodic_noise(size, rng, corr_px):
    """Tileable smooth noise in 0..1: white noise low-passed in Fourier space."""
    f = np.fft.fftfreq(size)
    fx, fy = np.meshgrid(f, f)
    kernel = np.exp(-(fx ** 2 + fy ** 2) * (math.pi * corr_px) ** 2 * 2.0)
    field = np.fft.ifft2(np.fft.fft2(rng.standard_normal((size, size))) * kernel).real
    field -= field.min()
    return field / max(field.max(), 1e-9)


def bake_micro(size, seed=SEED):
    """(normal RGB 0..1, film RGB 0..1), both tileable at `size`."""
    rng = np.random.default_rng(seed)       # same seed at every size: same layout
    height = np.zeros((size, size))
    count = 420
    # Scratch layout is drawn in unit UV so 256/512/1024 are the same pattern.
    for _ in range(count):
        cx, cy = rng.random(2)
        # most scratches follow the wipe direction (fore-aft polishing arcs)
        theta = rng.normal(0.0, 0.35) if rng.random() < 0.75 else rng.uniform(0, math.pi)
        length = rng.uniform(0.04, 0.30)
        depth = rng.uniform(0.25, 1.0)
        curve = rng.normal(0.0, 0.6)
        n = max(8, int(length * size * 1.5))
        s = np.linspace(-0.5, 0.5, n)
        ang = theta + curve * s
        x = (cx + np.cumsum(np.cos(ang)) * length / n) % 1.0
        y = (cy + np.cumsum(np.sin(ang)) * length / n) % 1.0
        fade = np.cos(s * math.pi) ** 2
        # scratch width is fixed in UV: size/256 texels, laid across the stroke
        for k in range(max(1, size // 256)):
            ox, oy = -np.sin(ang) * k / size, np.cos(ang) * k / size
            np.subtract.at(height, (((y + oy) * size).astype(int) % size,
                                    ((x + ox) * size).astype(int) % size), depth * fade)
    height = np.clip(height, -1.5, 0.0)
    # soften one texel so the normal is not pure aliasing
    soft = (height * 2 + np.roll(height, 1, 0) + np.roll(height, -1, 0)
            + np.roll(height, 1, 1) + np.roll(height, -1, 1)) / 6.0
    strength = 0.9
    dx = (np.roll(soft, -1, 1) - np.roll(soft, 1, 1)) * 0.5 * strength
    dy = (np.roll(soft, -1, 0) - np.roll(soft, 1, 0)) * 0.5 * strength
    nz = 1.0 / np.sqrt(dx * dx + dy * dy + 1.0)
    normal = np.stack([-dx * nz * 0.5 + 0.5, dy * nz * 0.5 + 0.5, nz * 0.5 + 0.5], -1)  # G down

    scratch = np.clip(-soft / 0.6, 0.0, 1.0)
    salt = _periodic_noise(size, rng, corr_px=size / 9.0)
    lo, hi = np.percentile(salt, [60.0, 99.5])                 # coverage fixed at every size
    salt = np.clip((salt - lo) / (hi - lo), 0.0, 1.0) ** 1.5   # patchy, 60 % of the pane clear
    fine = _periodic_noise(size, rng, corr_px=size / 90.0)
    salt = salt * (0.7 + 0.3 * fine)
    rough = np.clip(0.55 * salt + 0.45 * scratch, 0.0, 1.0)
    film = np.stack([rough, salt, scratch], -1)
    return normal, film


# -- prediction used by the source test (NOT a visual result) -------------------
def predicted_canopy_linear(cos_i, env_linear):
    """Opaque tier-0 canopy radiance for one view angle looking at `env_linear`."""
    r, _, _ = slab_terms(cos_i)
    return np.asarray(GLASS_TINT_LINEAR) + float(r) * np.asarray(env_linear)


def effective_albedo(coverage):
    c = min(max(coverage, 0.0), 1.0) * SALT_FILM_MAX_COVERAGE
    return [g * (1 - c) + SALT_FILM_ALBEDO * c for g in GLASS_TINT_LINEAR]


def mip_bytes(w, h, bytes_per_px):
    return int(w * h * bytes_per_px * 4 / 3)


def tier_vram_mb(tier):
    t = TIERS[tier]
    b = mip_bytes(LUT_W, 1, 4) + mip_bytes(t["env_w"], t["env_w"] // 2, 4)   # BGRA8, uncompressed
    if t["micro"]:
        b += mip_bytes(t["micro"], t["micro"], 1.0)     # BC5 normal, 1 byte/px
        b += mip_bytes(t["micro"], t["micro"], 0.5)     # BC1 film, 0.5 byte/px
    return round(b / 1048576, 3)


def _save(arr01, path):
    Image.fromarray((np.clip(arr01, 0, 1) * 255.0 + 0.5).astype(np.uint8)).save(path, optimize=True)


def bake(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    _save(bake_fresnel_lut(), out / "T_GlassFresnel_LUT.png")
    files["T_GlassFresnel_LUT.png"] = {"srgb": False, "compression": "TC_VectorDisplacementmap (BGRA8, no mips)"}
    env_cache = {}
    for w in sorted({t["env_w"] for t in TIERS.values()}):
        env_cache[w] = bake_env(w)
        name = f"T_GlassEnv_{w}.png"
        _save(srgb_encode(env_cache[w] / SHARED["env_encode_scale"]), out / name)
        files[name] = {"srgb": True, "compression": "TC_EditorIcon/UserInterface2D (BGRA8), clamp V, wrap U"}
    for s in sorted({t["micro"] for t in TIERS.values() if t["micro"]}):
        normal, film = bake_micro(s)
        _save(normal, out / f"T_GlassMicro_N_{s}.png")
        _save(film, out / f"T_GlassFilm_M_{s}.png")
        files[f"T_GlassMicro_N_{s}.png"] = {"srgb": False, "compression": "TC_Normalmap (BC5), flip green OFF"}
        files[f"T_GlassFilm_M_{s}.png"] = {"srgb": False, "compression": "TC_Masks (BC1 linear)"}
    for name in files:
        files[name]["sha256"] = hashlib.sha256((out / name).read_bytes()).hexdigest()
        files[name]["bytes"] = (out / name).stat().st_size

    env = env_cache[64]
    h = env.shape[0]
    sky_up = env[: h // 2].mean(axis=(0, 1))                # upper hemisphere mean
    pred = {f"{c:.2f}": round(float(srgb_encode(luma(predicted_canopy_linear(c, sky_up))) * 255), 1)
            for c in (1.0, 0.7, 0.4, 0.2, 0.1)}
    doc = {
        "visual_only": True,
        "measured": False,
        "shared_params": SHARED,
        "env_note": ENV_NOTE,
        "glass": {
            "ior": GLASS_IOR, "tint_linear": GLASS_TINT_LINEAR,
            "thin_transmittance": THIN_TRANSMITTANCE,
            "roughness_base": ROUGHNESS_BASE, "roughness_add_max": ROUGHNESS_ADD_MAX,
            "salt_film_albedo": SALT_FILM_ALBEDO, "salt_film_max_coverage": SALT_FILM_MAX_COVERAGE,
            "micro_tile_m": 0.35, "micro_normal_strength": {"1": 0.35, "2": 0.5, "3": 0.5},
            "albedo_range": ALBEDO_RANGE,
        },
        "tiers": {str(k): {**v, "est_vram_mb": tier_vram_mb(k)} for k, v in TIERS.items()},
        "predicted_opaque_canopy_srgb_luma_by_cos": pred,
        "current_opaque_canopy_srgb_luma_no_reflection":
            round(float(srgb_encode(luma(np.asarray(GLASS_TINT_LINEAR))) * 255), 1),
        "files": files,
        "seed": SEED,
    }
    (out / "glass_coastal.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return doc


# -- the pixel gate (run on Windows-rendered frames) ---------------------------
GATE = {
    "canopy_contrast_gain_min": 10.0,      # (p97 - p5) of canopy luma, candidate minus reference, /255
    "aircraft_p50_drop_max": 2.0,          # aircraft ROI luma p50 may not fall more than this, /255
    "canopy_black_fraction_max": 0.02,     # canopy pixels below 8/255
    "canopy_clip_fraction_max": 0.02,      # canopy pixels above 250/255
}


def _roi_luma(path, roi):
    img = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)
    x0, y0, x1, y1 = roi
    return luma(img[y0:y1, x0:x1])


def measure(ref, cand, canopy_roi, aircraft_roi):
    out = {}
    for tag, path in (("ref", ref), ("cand", cand)):
        c = _roi_luma(path, canopy_roi)
        a = _roi_luma(path, aircraft_roi)
        out[tag] = {
            "canopy_contrast": float(np.percentile(c, 97) - np.percentile(c, 5)),
            "canopy_black_fraction": float((c < 8).mean()),
            "canopy_clip_fraction": float((c > 250).mean()),
            "aircraft_p50": float(np.percentile(a, 50)),
        }
    gain = out["cand"]["canopy_contrast"] - out["ref"]["canopy_contrast"]
    drop = out["ref"]["aircraft_p50"] - out["cand"]["aircraft_p50"]
    checks = {
        "canopy_contrast_gain": gain >= GATE["canopy_contrast_gain_min"],
        "no_dark_aircraft_regression": drop <= GATE["aircraft_p50_drop_max"],
        "canopy_not_blacked_out": out["cand"]["canopy_black_fraction"] <= GATE["canopy_black_fraction_max"],
        "canopy_not_clipped": out["cand"]["canopy_clip_fraction"] <= GATE["canopy_clip_fraction_max"],
    }
    out.update({"canopy_contrast_gain": gain, "aircraft_p50_drop": drop,
                "thresholds": GATE, "checks": checks, "pass": all(checks.values())})
    return out


def _roi(text):
    v = [int(t) for t in text.split(",")]
    if len(v) != 4 or v[2] <= v[0] or v[3] <= v[1]:
        raise argparse.ArgumentTypeError("roi is x0,y0,x1,y1 with x1>x0 and y1>y0")
    return v


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bake")
    b.add_argument("--out", type=Path, default=HERE / "out")
    m = sub.add_parser("measure")
    m.add_argument("--ref", required=True)
    m.add_argument("--cand", required=True)
    m.add_argument("--canopy-roi", type=_roi, required=True)
    m.add_argument("--aircraft-roi", type=_roi, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "bake":
        doc = bake(a.out)
        print(json.dumps({k: v["sha256"][:12] for k, v in doc["files"].items()}, indent=1))
        return 0
    res = measure(a.ref, a.cand, a.canopy_roi, a.aircraft_roi)
    print(json.dumps(res, indent=1))
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
