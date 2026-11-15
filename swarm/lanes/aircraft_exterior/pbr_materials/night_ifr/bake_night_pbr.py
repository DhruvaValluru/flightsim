"""Offline bake of the night-IFR airframe surface textures (VISUAL-ONLY).

Lane aircraft_exterior.pbr_materials.night_ifr. Runs on the Mac
(numpy + Pillow, no GPU, no Unreal); the laptop's render path only samples
what this writes. It replaces, for the night scenario, the per-pixel
procedural panel/wear/grime maths of the paint and bare_metal masters
(assets/shaders/aircraft/panel_lines.hlsl, aircraft_wear.hlsl) with two
tileable textures and a hand-built mip chain:

* ``T_AcNight_ORM_<size>.dds``  R = groove ambient occlusion,
  G = roughness (absolute, about BAKED_BASE_ROUGHNESS), B = albedo gain
  (grime / streak darkening, never below MIN_ALBEDO_GAIN). BC1 on import.
* ``T_AcNight_N_<size>.dds``    tangent-space normal (grooves, oil-canning
  pillows, rivet dimples at the sizes whose texel can hold one). BC5 on import.

What the mip chain adds that the engine's own mip generation does not: each
roughness mip is widened by the variance of the normals it averages
(Toksvig 2005 for the variance from the shortened mean normal; the
kernel clamp of Tokuyoshi & Kaplanyan 2019). At night the frame is a dark
airframe under a few very small, very bright lamps (runway edge lights,
nav lights, the moon); a groove normal that minifies without widening the
lobe is what makes those glints crawl. No extra shader cost: it is in the
mips.

The dark-aircraft guard is structural, not a tuned number: occlusion goes
to the AO pin only (never multiplied into base colour), the albedo gain is
bounded below by MIN_ALBEDO_GAIN, and :func:`night_albedo` clamps the
final base colour into [ALBEDO_MIN, ALBEDO_MAX].

Nothing here has been rendered. Every look number is UNCALIBRATED until
the pixel gate in INTEGRATION.md has run on the Windows laptop.

    .venv/bin/python swarm/lanes/aircraft_exterior/pbr_materials/night_ifr/bake_night_pbr.py \
        --out swarm/lanes/aircraft_exterior/pbr_materials/night_ifr/baked --tiers 0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

SCHEMA = "flightsim-swarm-night-pbr/1"
VISUAL_ONLY = "visual-only: no label, FDM or sensing record reads these textures"
UNCALIBRATED = "UNCALIBRATED: set by the pixel gate on the Windows laptop"
SEED = 20261112

#: One texture period in centimetres of airframe surface. The paint
#: master's PanelPitchCm is (120, 90, 45) (scripts/aircraft_look.py
#: CLASS_VECTORS); 360 is their least common multiple, so the baked grid
#: lands where the procedural one did.
PERIOD_CM = 360.0
PANEL_PITCH_CM = (120.0, 90.0)
PANEL_WIDTH_CM = 0.35          # CLASS_SCALARS["paint"]["PanelWidthCm"]
GROOVE_DEPTH_CM = 0.05         # look choice, at the true width
#: A size too coarse for the true width draws a wider groove; its depth
#: grows with it (up to this) so the wall slope, which is what the normal
#: and the specular widening see, does not fade with the tier.
GROOVE_DEPTH_MAX_CM = 0.25
OILCAN_DEPTH_CM = 0.04         # look choice: skin pillowing between frames
RIVET_PITCH_CM = 3.0
RIVET_RADIUS_CM = 0.3
RIVET_DEPTH_CM = 0.008
RIVET_MAX_TEXEL_CM = 0.2       # a dimple needs 3 texels across; coarser sizes bake none

#: The roughness the G channel is baked about: the J-11A look config's paint
#: Roughness (assets/aircraft_config/look/J11.json class_scalars.paint). The
#: material adds (its own Roughness - this), so another type keeps its own base.
BAKED_BASE_ROUGHNESS = 0.5
ROUGHNESS_BREAKUP = 0.12       # CLASS_SCALARS["paint"]["RoughnessBreakup"]
GRIME_ROUGHNESS = 0.18         # grime is matter than paint
ROUGHNESS_MIN, ROUGHNESS_MAX = 0.08, 1.0
#: Tokuyoshi & Kaplanyan 2019, "Improved Geometric Specular Antialiasing":
#: the kernel's squared-roughness contribution is clamped at 0.18.
SPECULAR_AA_CLAMP = 0.18

#: Base-colour bounds, linear sRGB. The floor is the darkest measured row
#: the repo already uses (Physically Based database "Tire", albedo 0.023,
#: scripts/aircraft_look.py TIRE_ALBEDO); the ceiling is the paint master's
#: AlbedoMax (0.9). Nothing an airframe is painted with is outside them.
ALBEDO_MIN = 0.023
ALBEDO_MAX = 0.9
#: The most the baked grime may darken base colour. With occlusion kept out
#: of base colour this bounds the whole baked darkening: a 0.2 grey stays
#: at or above 0.13.
MIN_ALBEDO_GAIN = 0.65
AO_MIN = 0.55                  # groove floor on the AO pin

TIER_SIZES = {0: 512, 1: 1024, 2: 2048, 3: 4096}
#: Render-side description per tier (INTEGRATION.md has the graph). VRAM is
#: an ESTIMATE from the block-compressed sizes with a full mip chain
#: (BC1 0.5 byte/texel, BC5 1 byte/texel, x 4/3); no tier is claimed sustained.
TIERS = {
    0: {"normal_map": False, "projections": 2, "clear_coat": False, "procedural_wear": False,
        "summary": "512 ORM only (BC1), two planar projections picked by the vertex normal, "
                   "Default Lit, no clear coat, no per-pixel procedural wear/panel maths"},
    1: {"normal_map": True, "projections": 2, "clear_coat": False, "procedural_wear": False,
        "summary": "1024 ORM (BC1) + normal (BC5), two planar projections, Default Lit"},
    2: {"normal_map": True, "projections": 3, "clear_coat": True, "procedural_wear": False,
        "summary": "2048 ORM + normal, full triplanar, the paint master's Clear Coat shading "
                   "model at the type's own ClearCoat value (J-11A: 0)"},
    3: {"normal_map": True, "projections": 3, "clear_coat": True, "procedural_wear": True,
        "summary": "4096 ORM + normal, triplanar, Clear Coat model, and the existing procedural "
                   "edge wear and exhaust soot kept on top"},
}


def vram_estimate_mb(tier: int) -> float:
    size = TIER_SIZES[tier]
    texels = size * size * 4.0 / 3.0
    total = texels * 0.5 + (texels * 1.0 if TIERS[tier]["normal_map"] else 0.0)
    return round(total / (1024.0 * 1024.0), 2)


# -- colour ------------------------------------------------------------------

def srgb_encode(linear):
    v = np.clip(np.asarray(linear, dtype=np.float64), 0.0, 1.0)
    return np.where(v <= 0.0031308, 12.92 * v, 1.055 * np.power(v, 1.0 / 2.4) - 0.055)


def night_albedo(base_linear, gain=1.0):
    """The base colour the night material outputs: the type's own colour
    times the baked gain, clamped into the calibrated range. This is the
    exact expression INTEGRATION.md asks the material graph to build."""
    gain = np.clip(np.asarray(gain, dtype=np.float64), MIN_ALBEDO_GAIN, 1.0)
    return np.clip(np.asarray(base_linear, dtype=np.float64) * gain, ALBEDO_MIN, ALBEDO_MAX)


# -- tileable fields -----------------------------------------------------------

def spectral_noise(size: int, rng, beta: float, stretch_x: float = 1.0, low_cut: float = 1.0):
    """Tileable noise in [0, 1]: white noise shaped in the Fourier domain
    (power ~ 1/f^beta), so it wraps exactly. ``stretch_x`` > 1 smears it
    along +X (the airflow: aft-running streaks)."""
    white = rng.standard_normal((size, size))
    fy = np.fft.fftfreq(size)[:, None] * size
    fx = np.fft.rfftfreq(size)[None, :] * size
    radius = np.sqrt((fx * stretch_x) ** 2 + fy ** 2)
    shape = np.where(radius >= low_cut, np.power(np.maximum(radius, 1e-6), -beta / 2.0), 0.0)
    field = np.fft.irfft2(np.fft.rfft2(white) * shape, s=(size, size))
    field = (field - field.mean()) / (field.std() + 1e-12)
    return np.clip(0.5 + field / 6.0, 0.0, 1.0)


def _line_distance_cm(coord_cm, pitch_cm):
    return np.abs((coord_cm + pitch_cm / 2.0) % pitch_cm - pitch_cm / 2.0)


def _smooth(edge0, edge1, x):
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def build_fields(size: int, seed: int = SEED):
    """Mip 0 of everything, as float arrays: height (cm), ao, roughness, gain."""
    rng = np.random.default_rng(seed)
    texel = PERIOD_CM / size
    axis = (np.arange(size) + 0.5) * texel
    x, y = np.meshgrid(axis, axis)                       # x along the airflow
    dx = _line_distance_cm(x, PANEL_PITCH_CM[0])
    dy = _line_distance_cm(y, PANEL_PITCH_CM[1])
    dist = np.minimum(dx, dy)
    half = max(PANEL_WIDTH_CM / 2.0, 0.75 * texel)       # a groove is never thinner than 1.5 texels
    groove = 1.0 - _smooth(half * 0.5, half * 1.5, dist)

    # Oil-canning: each panel bows between its frames, by a per-panel amount.
    nx, ny = int(PERIOD_CM / PANEL_PITCH_CM[0]), int(PERIOD_CM / PANEL_PITCH_CM[1])
    amount = rng.uniform(-1.0, 1.0, size=(ny, nx))
    cell = amount[(y // PANEL_PITCH_CM[1]).astype(int) % ny, (x // PANEL_PITCH_CM[0]).astype(int) % nx]
    u = (x % PANEL_PITCH_CM[0]) / PANEL_PITCH_CM[0]
    v = (y % PANEL_PITCH_CM[1]) / PANEL_PITCH_CM[1]
    pillow = np.sin(np.pi * u) * np.sin(np.pi * v) * cell

    depth = min(GROOVE_DEPTH_CM * half / (PANEL_WIDTH_CM / 2.0), GROOVE_DEPTH_MAX_CM)
    height = -depth * groove + OILCAN_DEPTH_CM * pillow
    rivets = texel <= RIVET_MAX_TEXEL_CM
    if rivets:
        # A row each side of every line, RIVET_PITCH_CM apart, 1.5 cm off the line.
        along_x = _line_distance_cm(x, RIVET_PITCH_CM)
        along_y = _line_distance_cm(y, RIVET_PITCH_CM)
        r1 = np.hypot(along_x, np.abs(dy - 1.5))
        r2 = np.hypot(along_y, np.abs(dx - 1.5))
        dimple = 1.0 - _smooth(RIVET_RADIUS_CM * 0.5, RIVET_RADIUS_CM, np.minimum(r1, r2))
        height = height - RIVET_DEPTH_CM * dimple

    breakup = spectral_noise(size, rng, beta=2.2, low_cut=2.0)
    streaks = spectral_noise(size, rng, beta=2.0, stretch_x=0.12, low_cut=2.0)   # long in X
    seam_dirt = np.exp(-dist / 4.0)                      # dirt gathers within ~4 cm of a seam
    grime = np.clip(0.55 * _smooth(0.45, 0.8, streaks) + 0.5 * seam_dirt * breakup, 0.0, 1.0)

    ao = 1.0 - (1.0 - AO_MIN) * groove
    roughness = np.clip(BAKED_BASE_ROUGHNESS + ROUGHNESS_BREAKUP * (breakup - 0.5) * 2.0
                        + GRIME_ROUGHNESS * grime, ROUGHNESS_MIN, ROUGHNESS_MAX)
    gain = 1.0 - (1.0 - MIN_ALBEDO_GAIN) * grime
    return {"height": height, "ao": ao, "roughness": roughness, "gain": gain,
            "texel_cm": texel, "rivets": bool(rivets)}


def normals_from_height(height, texel_cm: float):
    """Unit tangent-space normals from a periodic height field (central
    differences that wrap, so the normal map tiles like the height)."""
    ddx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) / (2.0 * texel_cm)
    ddy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) / (2.0 * texel_cm)
    n = np.stack([-ddx, -ddy, np.ones_like(height)], axis=-1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


# -- the mip chain ---------------------------------------------------------------

def _box(a):
    return 0.25 * (a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2])


def widen_roughness(roughness, mean_normal_length):
    """Roughness after folding the normal variance of the footprint into the
    lobe: alpha^2 += min(2 sigma^2, clamp), sigma^2 = (1 - |n|) / |n|
    (alpha = roughness^2, UE's convention)."""
    length = np.clip(mean_normal_length, 1e-4, 1.0)
    sigma2 = (1.0 - length) / length
    alpha2 = np.power(roughness, 4.0) + np.minimum(2.0 * sigma2, SPECULAR_AA_CLAMP)
    return np.clip(np.power(alpha2, 0.25), ROUGHNESS_MIN, ROUGHNESS_MAX)


def build_mips(fields):
    """[(orm float HxWx3, normal float HxWx3 unit, mean normal length)] from
    mip 0 down to 1x1. Roughness is averaged as alpha^2 and then widened by
    the variance of the mip-0 normals under each texel."""
    n0 = normals_from_height(fields["height"], fields["texel_cm"])
    ao, gain = fields["ao"], fields["gain"]
    alpha2 = np.power(fields["roughness"], 4.0)
    nsum = n0.copy()
    mips = []
    while True:
        length = np.linalg.norm(nsum, axis=-1)
        rough = widen_roughness(np.power(alpha2, 0.25), length)
        unit = nsum / np.maximum(length, 1e-6)[..., None]
        mips.append((np.stack([ao, rough, gain], axis=-1), unit, length))
        if ao.shape[0] == 1:
            return mips
        ao, gain, alpha2 = _box(ao), _box(gain), _box(alpha2)
        nsum = _box(nsum)


# -- DDS -------------------------------------------------------------------------

DDS_MAGIC = b"DDS "
_DDSD = 0x1 | 0x2 | 0x4 | 0x8 | 0x1000 | 0x20000      # caps height width pitch pixelformat mipmapcount
_DDPF_RGBA = 0x40 | 0x1
_CAPS = 0x1000 | 0x8 | 0x400000                        # texture complex mipmap


def _to_u8(a):
    return np.clip(np.rint(np.asarray(a) * 255.0), 0, 255).astype(np.uint8)


def dds_bytes(levels) -> bytes:
    """An uncompressed B8G8R8A8 DDS with every mip supplied. Uncompressed on
    purpose: the block compression (BC1 / BC5) happens once, on import, in
    the engine's own compressor; with MipGenSettings = LeaveExistingMips the
    importer keeps this chain instead of rebuilding it."""
    h, w = levels[0].shape[:2]
    header = struct.pack("<7I", 124, _DDSD, h, w, w * 4, 0, len(levels)) + b"\0" * 44
    header += struct.pack("<8I", 32, _DDPF_RGBA, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    header += struct.pack("<5I", _CAPS, 0, 0, 0, 0)
    body = b""
    for rgb in levels:
        bgra = np.concatenate([rgb[..., ::-1], np.full(rgb.shape[:2] + (1,), 255, np.uint8)], axis=-1)
        body += bgra.tobytes()
    return DDS_MAGIC + header + body


def read_dds(data: bytes):
    """Back to a list of HxWx3 uint8 RGB levels (the test's round trip, and
    measure_gate.py does not need it)."""
    if data[:4] != DDS_MAGIC:
        raise ValueError("not a DDS")
    _, _, h, w, _, _, count = struct.unpack_from("<7I", data, 4)
    offset, levels = 128, []
    for _ in range(count):
        block = np.frombuffer(data, np.uint8, h * w * 4, offset).reshape(h, w, 4)
        levels.append(block[..., 2::-1].copy())
        offset += h * w * 4
        h, w = max(1, h // 2), max(1, w // 2)
    return levels


def encode(mips):
    orm = [_to_u8(m[0]) for m in mips]
    normal = [_to_u8(m[1] * 0.5 + 0.5) for m in mips]
    return orm, normal


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -- the bake ----------------------------------------------------------------------

def bake_tier(tier: int, out: Path, size: int = 0, seed: int = SEED) -> dict:
    size = size or TIER_SIZES[tier]
    fields = build_fields(size, seed)
    mips = build_mips(fields)
    orm, normal = encode(mips)
    record = {"tier": tier, "size": size, "texel_cm": fields["texel_cm"],
              "rivets_baked": fields["rivets"], "mips": len(mips),
              "est_vram_mb": vram_estimate_mb(tier), "vram_is": "ESTIMATE, not measured",
              **TIERS[tier], "textures": {}}
    out.mkdir(parents=True, exist_ok=True)
    wanted = [("orm", orm, f"T_AcNight_ORM_{size}.dds", "BC1 (DXT1), sRGB OFF, Masks")]
    if TIERS[tier]["normal_map"]:
        wanted.append(("normal", normal, f"T_AcNight_N_{size}.dds", "BC5, Normalmap"))
    for key, levels, name, compression in wanted:
        data = dds_bytes(levels)
        (out / name).write_bytes(data)
        record["textures"][key] = {"file": name, "sha256": sha256(data), "bytes": len(data),
                                   "import_compression": compression,
                                   "mip_gen": "LeaveExistingMips"}
    record["stats"] = {
        "ao_min": float(mips[0][0][..., 0].min()),
        "roughness_mip0_mean": float(mips[0][0][..., 1].mean()),
        "roughness_last_mip": float(mips[-1][0][..., 1].mean()),
        "gain_min": float(mips[0][0][..., 2].min()),
        "normal_z_min": float(mips[0][1][..., 2].min()),
    }
    return record


def manifest(records) -> dict:
    return {
        "schema": SCHEMA, "scenario": "night_ifr", "item": "aircraft_exterior.pbr_materials.night_ifr",
        "label": VISUAL_ONLY, "calibration": UNCALIBRATED, "seed": SEED,
        "numpy": np.__version__,
        "period_cm": PERIOD_CM, "panel_pitch_cm": list(PANEL_PITCH_CM),
        "channels": {"orm": {"R": "ambient occlusion (AO pin only, never base colour)",
                             "G": f"roughness, baked about {BAKED_BASE_ROUGHNESS}",
                             "B": f"albedo gain in [{MIN_ALBEDO_GAIN}, 1]"},
                     "normal": "tangent space, +Z out, X along the airflow"},
        "material": {
            "albedo_min_linear": ALBEDO_MIN, "albedo_max_linear": ALBEDO_MAX,
            "albedo_min_srgb8": int(round(float(srgb_encode(ALBEDO_MIN)) * 255)),
            "albedo_max_srgb8": int(round(float(srgb_encode(ALBEDO_MAX)) * 255)),
            "min_albedo_gain": MIN_ALBEDO_GAIN, "ao_min": AO_MIN,
            "baked_base_roughness": BAKED_BASE_ROUGHNESS,
            "roughness_expression": "saturate(G + (Roughness - baked_base_roughness))",
            "base_colour_expression": "clamp(Base * lerp(1, B, GrimeScale), albedo_min, albedo_max)",
            "specular": 0.5, "metallic_paint": 0.0,
        },
        "tiers": records,
    }


def main(argv=None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=here / "baked")
    parser.add_argument("--tiers", default="0", help="comma list of 0-3, or 'all'")
    args = parser.parse_args(argv)
    tiers = sorted(TIER_SIZES) if args.tiers == "all" else [int(t) for t in args.tiers.split(",")]
    records = [bake_tier(t, args.out) for t in tiers]
    path = args.out / "night_pbr.json"
    path.write_text(json.dumps(manifest(records), indent=2) + "\n", encoding="utf-8")
    for r in records:
        print(f"tier {r['tier']}: {r['size']} px, {r['mips']} mips, est {r['est_vram_mb']} MB (estimate)")
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
