"""Offline bake for the alpine airframe wear and stencil layer. VISUAL ONLY.

Runs on the Mac (numpy + stdlib). The laptop only samples what this writes:

  T_AlpineWear_Mask.png   RGB8 linear, tileable. R = airflow grime streaks
                          (long along U = the object's -X, aft), G = paint
                          chips, B = rime/frost breakup.
  T_AlpineWear_N.png      RGB8 tangent normal (oil-canning + orange peel),
                          tileable, tier >= 1. No panel lines or rivets: those
                          need the airframe's own UVs and are NOT delivered.
  T_AlpineWear_Soot.png   G8 exhaust deposition LUT (u = distance aft of the
                          exit, v = lateral offset), tier >= 1.
  T_AlpineWear_Decals.png G8 coverage atlas, four 512x64 rows: NO STEP,
                          NO PUSH, LIFT HERE, static-port ring. Own 5x7
                          glyphs; no font file, no registration mark.

The textures are projected in the airframe's object space (alpine_wear.ush),
so nothing here depends on a mesh's UV layout.

`apply_wear` is the numpy mirror of the shader's base-colour arithmetic; the
test uses it to hold the "no dark aircraft" guard on the baked masks.

    .venv/bin/python swarm/lanes/aircraft_exterior/decals_wear/alpine/bake_decals_wear.py --tier 0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

SEED = 20261112
LANE = Path(__file__).resolve().parent
STAMP = "UNCALIBRATED: set by probe render on the render machine"

#: Texture edge per tier (mask and normal).
TIER_SIZE = {0: 512, 1: 512, 2: 1024, 3: 2048}

#: Shader constants. Names are the master-material scalar/vector names and the
#: identifiers in alpine_wear.ush (pinned by the test). All UNCALIBRATED.
PARAMS: Dict[str, object] = {
    "WearTileCm": 180.0,            # one tile of the mask spans 1.8 m of airframe
    "GrimeAmount": 0.55,
    "GrimeTint": (0.80, 0.78, 0.74),  # multiplicative film, never below this
    "ChipAmount": 0.50,
    "PrimerAlbedo": (0.42, 0.44, 0.36),
    "FrostAmount": 0.0,             # 0 unless the card carries an icing schedule
    "FrostAlbedo": 0.80,            # rime, same value as the shared snow albedo
    "FrostExponent": 3.0,           # leading-edge falloff on dot(N, +X)
    "SootAmount": 0.80,
    "SootAlbedo": 0.04,
    "WearFloorRatio": 0.72,         # wear may not take base colour below 72 %
    "SootFloorRatio": 0.15,         # inside the soot plume only
    "AlbedoMin": 0.04,              # charcoal; wear never goes below (unless the paint does)
    "AlbedoMax": 0.90,              # fresh snow; wear never goes above (unless the paint does)
    "GrimeRoughness": 0.25,
    "ChipRoughness": 0.20,
    "FrostRoughness": 0.45,
    "WearNormalStrength": 0.35,
    "DecalAlbedo": 0.05,            # stencil ink, matt black
    "DecalWear": 0.60,              # how much chips eat the stencil
}

DECAL_ROWS = ("NO STEP", "NO PUSH", "LIFT HERE", "@ring")
DECAL_ROW_PX = (512, 64)

_GLYPHS = {
    "N": "10001 11001 10101 10011 10001 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110",
    "S": "01111 10000 10000 01110 00001 00001 11110",
    "T": "11111 00100 00100 00100 00100 00100 00100",
    "E": "11111 10000 10000 11110 10000 10000 11111",
    "P": "11110 10001 10001 11110 10000 10000 10000",
    "U": "10001 10001 10001 10001 10001 10001 01110",
    "H": "10001 10001 10001 11111 10001 10001 10001",
    "L": "10000 10000 10000 10000 10000 10000 11111",
    "I": "01110 00100 00100 00100 00100 00100 01110",
    "F": "11111 10000 10000 11110 10000 10000 10000",
    "R": "11110 10001 10001 11110 10100 10010 10001",
    " ": "00000 00000 00000 00000 00000 00000 00000",
}


# ----------------------------------------------------------------- noise

def _freqs(n: int) -> Tuple[np.ndarray, np.ndarray]:
    f = np.fft.fftfreq(n) * n  # cycles per tile
    return f[None, :], f[:, None]


def _noise(rng: np.random.Generator, n: int, transfer: np.ndarray) -> np.ndarray:
    """Spectrally shaped white noise: periodic (tileable) by construction."""
    out = np.fft.ifft2(np.fft.fft2(rng.standard_normal((n, n))) * transfer).real
    out -= out.mean()
    return out / (out.std() + 1e-12)


def _soft(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def bake_mask(n: int, seed: int = SEED) -> np.ndarray:
    """(n, n, 3) float in [0, 1]: grime streaks, chips, frost breakup."""
    rng = np.random.default_rng(seed)
    fx, fy = _freqs(n)
    r = np.hypot(fx, fy)
    # Grime: a uniform-flow line integral convolution is an anisotropic
    # low-pass, long along U (aft). Broken up by a slow blotch field.
    streak = _noise(rng, n, np.exp(-(fx / 3.0) ** 2 - (fy / 70.0) ** 2) * (np.abs(fy) > 3))
    blotch = _noise(rng, n, np.exp(-(r / 4.0) ** 2) * (r > 0))
    grime = _soft(streak + 0.6 * blotch, 0.2, 1.8)
    # Chips: sparse high-frequency flecks (about the top 7 % of the field).
    chip_n = _noise(rng, n, np.exp(-((r - 45.0) / 18.0) ** 2))
    lo = float(np.quantile(chip_n, 0.93))
    chips = _soft(chip_n, lo, lo + 0.35)
    # Frost: ridged clumps with a fine crystalline grain.
    clump = np.abs(_noise(rng, n, np.exp(-((r - 10.0) / 6.0) ** 2)))
    grain = _noise(rng, n, np.exp(-((r - 90.0) / 30.0) ** 2))
    frost = np.clip(_soft(clump, 0.1, 1.4) * (0.75 + 0.25 * np.tanh(grain)), 0.0, 1.0)
    return np.stack([grime, chips, frost], axis=-1)


def bake_normal(n: int, seed: int = SEED, strength: float = 1.0) -> np.ndarray:
    """(n, n, 3) unit tangent normals: oil-canning plus orange peel."""
    rng = np.random.default_rng(seed + 1)
    fx, fy = _freqs(n)
    r = np.hypot(fx, fy)
    height = _noise(rng, n, np.exp(-((r - 5.0) / 2.5) ** 2))
    height = height + 0.04 * _noise(rng, n, np.exp(-((r - 120.0) / 40.0) ** 2))
    # Periodic central differences; slope scaled so it is size-independent.
    k = strength * 0.012 * n / (2.0 * np.pi)
    dx = (np.roll(height, -1, 1) - np.roll(height, 1, 1)) * 0.5 * k
    dy = (np.roll(height, -1, 0) - np.roll(height, 1, 0)) * 0.5 * k
    nrm = np.stack([-dx, -dy, np.ones_like(dx)], axis=-1)
    return nrm / np.linalg.norm(nrm, axis=-1, keepdims=True)


def bake_soot(width: int = 256, height: int = 64, half_angle_deg: float = 7.0,
              decay: float = 0.35, exit_width: float = 0.06) -> np.ndarray:
    """(height, width) deposition in [0, 1]: a spreading cone decaying aft.

    u in [0, 1] is distance aft of the exhaust exit over the plume length;
    v in [-0.5, 0.5] the lateral offset over the same length.
    """
    u = (np.arange(width) + 0.5) / width
    v = (np.arange(height) + 0.5) / height - 0.5
    sigma = exit_width + u * np.tan(np.radians(half_angle_deg))
    core = np.exp(-0.5 * (v[:, None] / sigma[None, :]) ** 2)
    along = np.exp(-u / decay) * _soft(u, 0.0, 0.03) * (1.0 - _soft(u, 0.85, 1.0))
    return np.clip(core * along[None, :], 0.0, 1.0)


def _text_row(text: str, size: Tuple[int, int]) -> np.ndarray:
    w, h = size
    scale = 8
    row = np.zeros((h, w))
    cols = len(text) * 6 - 1
    x0, y0 = (w - cols * scale) // 2, (h - 7 * scale) // 2
    if x0 < 0:
        raise ValueError(f"stencil {text!r} does not fit a {w}px row")
    for i, ch in enumerate(text):
        for j, bits in enumerate(_GLYPHS[ch].split()):
            for k, bit in enumerate(bits):
                if bit == "1":
                    y, x = y0 + j * scale, x0 + (i * 6 + k) * scale
                    row[y:y + scale, x:x + scale] = 1.0
    return row


def bake_decals() -> np.ndarray:
    """(256, 512) stencil coverage in [0, 1], one stencil per 64-px row."""
    w, h = DECAL_ROW_PX
    rows = []
    for name in DECAL_ROWS:
        if name == "@ring":
            y, x = np.mgrid[0:h, 0:w]
            d = np.hypot(x - w / 2 + 0.5, y - h / 2 + 0.5)
            row = ((d > 20) & (d < 28)).astype(float)
        else:
            row = _text_row(name, (w, h))
        rows.append(row)
    atlas = np.vstack(rows)
    # 3x3 box filter: one texel of edge softening for the bilinear sampler.
    pad = np.pad(atlas, 1)
    return sum(pad[i:i + atlas.shape[0], j:j + atlas.shape[1]]
               for i in range(3) for j in range(3)) / 9.0


# ---------------------------------------------- shader arithmetic, mirrored

def apply_wear(albedo, grime, chips, frost=0.0, soot=0.0, decal=0.0, params=None):
    """Base colour after wear. Mirrors AlpineWearBaseColor in alpine_wear.ush.

    `albedo` is linear RGB (..., 3); the masks are already placement-weighted
    scalars in [0, 1] broadcastable to albedo[..., 0].
    """
    p = dict(PARAMS, **(params or {}))
    a0 = np.asarray(albedo, dtype=float)
    ex = lambda m: np.asarray(m, dtype=float)[..., None]  # noqa: E731
    g, c, f, s, d = (ex(m) for m in (grime, chips, frost, soot, decal))
    a = a0 * (1.0 + (np.asarray(p["GrimeTint"]) - 1.0) * g * p["GrimeAmount"])
    a = a + (np.asarray(p["PrimerAlbedo"]) - a) * c * p["ChipAmount"]
    ink = d * (1.0 - p["DecalWear"] * c)
    a = a + (p["DecalAlbedo"] - a) * ink
    a = a + (p["FrostAlbedo"] - a) * f
    dark = np.clip(s * p["SootAmount"] + ink, 0.0, 1.0)  # where darkening is the point
    a = a + (p["SootAlbedo"] - a) * s * p["SootAmount"]
    floor = a0 * (p["WearFloorRatio"] + (p["SootFloorRatio"] - p["WearFloorRatio"]) * dark)
    a = np.maximum(a, floor)
    return np.clip(a, np.minimum(a0, p["AlbedoMin"]), np.maximum(a0, p["AlbedoMax"]))


def luminance(rgb) -> np.ndarray:
    return np.asarray(rgb, dtype=float) @ np.array([0.2126, 0.7152, 0.0722])


# ------------------------------------------------------------------- PNG

def write_png(path: Path, image: np.ndarray) -> str:
    """8-bit grey (H, W) or RGB (H, W, 3) PNG, stdlib only. Returns sha256."""
    img = np.asarray(image)
    if img.dtype != np.uint8:
        img = np.clip(np.rint(img * 255.0), 0, 255).astype(np.uint8)
    h, w = img.shape[:2]
    ctype = 0 if img.ndim == 2 else 2
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    blob = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
    return hashlib.sha256(blob).hexdigest()


def bake(tier: int, out_dir: Path, seed: int = SEED) -> Dict:
    n = TIER_SIZE[tier]
    out = Path(out_dir)
    files = {"T_AlpineWear_Mask.png": write_png(out / "T_AlpineWear_Mask.png", bake_mask(n, seed))}
    if tier >= 1:
        nrm = bake_normal(n, seed) * 0.5 + 0.5
        files["T_AlpineWear_N.png"] = write_png(out / "T_AlpineWear_N.png", nrm)
        files["T_AlpineWear_Soot.png"] = write_png(out / "T_AlpineWear_Soot.png", bake_soot())
        files["T_AlpineWear_Decals.png"] = write_png(out / "T_AlpineWear_Decals.png", bake_decals())
    manifest = {
        "lane": "aircraft_exterior.decals_wear.alpine", "visual_only": True, "tier": tier,
        "seed": seed, "size": n, "numpy": np.__version__, "sha256": files,
        "decal_rows": list(DECAL_ROWS),
        "wear": {"group": "wear", "constants": PARAMS, "stamp": STAMP},
    }
    (out / "bake_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tier", type=int, choices=sorted(TIER_SIZE), default=0)
    ap.add_argument("--out", default=None, help="default: <lane>/out/tier<N>")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args(argv)
    out = Path(args.out) if args.out else LANE / "out" / f"tier{args.tier}"
    manifest = bake(args.tier, out, args.seed)
    for name, digest in manifest["sha256"].items():
        print(f"{digest}  {out / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
