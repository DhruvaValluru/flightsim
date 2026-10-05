"""Tangent-space normal maps derived from the drape's albedo textures.

The simulator's terrain textures come with their own normal maps, named by
the ``.ter`` files; the committed extraction pulled none (see
``assets/xplane/README.md``), so every role rendered with a flat normal
and rock read as flat paint. Until ``scripts/extract_xplane.py`` is run on
the machine with the install, this derives a stand-in from the texture
itself: luminance, high-passed so broad colour changes are not read as
slopes, taken as height, and its wrapped gradient (the textures tile) as
the normal. An extracted normal always wins (``core/xplane/drape.py``).

Encoding: R = x (texture right), G = y toward the image's bottom row
(the DirectX convention, the one the engine's TC_Normalmap sampler
expects), B = z, each ``0.5 + 0.5 * n`` in 8 bits. Dark is taken as
low, which suits crevices and shadowed faces and is wrong where a
texture is dark for its colour alone; the relief per role is therefore
kept modest (``TARGET_MEAN_TILT_DEG``), and recorded.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import numpy as np
from PIL import Image

#: Mean surface tilt, in degrees, each role's derived normal is scaled
#: to: rock and cliff carry the most relief, flat ground the least. A
#: tilt rather than a height so the strength does not change when the
#: texture's resolution does (the 2048 px re-pull). Chosen by eye, not
#: measured.
TARGET_MEAN_TILT_DEG: Dict[str, float] = {"valley": 4.0, "scrub": 7.0,
                                          "rock": 14.0, "cliff": 18.0,
                                          "snow": 5.0}
#: Box-blur radius in texels for the high-pass (the broad colour removed).
HIGHPASS_RADIUS_PX = 12
SUFFIX = "_nrm_derived.png"


def _box_blur_wrap(a: np.ndarray, radius: int) -> np.ndarray:
    out = a
    for axis in (0, 1):
        acc = np.zeros_like(out)
        for shift in range(-radius, radius + 1):
            acc += np.roll(out, shift, axis=axis)
        out = acc / (2 * radius + 1)
    return out


def derive_normal(rgb: np.ndarray, metres_x: float, metres_y: float,
                  mean_tilt_deg: float) -> np.ndarray:
    """An (H, W, 3) uint8 normal map from an (H, W, 3) sRGB texture that
    tiles over ``metres_x`` by ``metres_y``, its relief scaled so the
    mean tilt is about ``mean_tilt_deg``."""
    v = np.asarray(rgb, dtype=np.float64)[..., :3] / 255.0
    lin = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
    luma = lin @ np.array([0.2126, 0.7152, 0.0722])
    luma = luma ** (1.0 / 2.2)                       # perceptual: crevices show
    height = luma - _box_blur_wrap(luma, HIGHPASS_RADIUS_PX)
    h, w = height.shape
    dx_m, dy_m = metres_x / w, metres_y / h
    # wrapped central differences; y runs down the image rows (DirectX)
    dhdx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) / (2 * dx_m)
    dhdy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) / (2 * dy_m)
    slope = np.hypot(dhdx, dhdy)
    mean_slope = float(np.mean(slope))
    k = (np.tan(np.radians(mean_tilt_deg)) / mean_slope) if mean_slope > 0 else 0.0
    n = np.stack([-k * dhdx, -k * dhdy, np.ones_like(height)], axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return np.clip(np.round((n * 0.5 + 0.5) * 255.0), 0, 255).astype(np.uint8)


def derive_drape_normals(drape_dir: Path) -> Dict[str, Dict[str, object]]:
    """Write ``<role>_nrm_derived.png`` beside each drape texture the
    index names; returns what was written, per role."""
    import json

    drape_dir = Path(drape_dir)
    index = json.loads((drape_dir / "drape_textures.json").read_text())
    written: Dict[str, Dict[str, object]] = {}
    for role, entry in index.items():
        if not isinstance(entry, dict) or "file" not in entry:
            continue
        relief = TARGET_MEAN_TILT_DEG.get(role, 6.0)
        rgb = np.asarray(Image.open(drape_dir / entry["file"]).convert("RGB"))
        nrm = derive_normal(rgb, float(entry["metres_x"]), float(entry["metres_y"]),
                            relief)
        out = drape_dir / f"{role}{SUFFIX}"
        Image.fromarray(nrm).save(out, optimize=True)
        z = np.clip(nrm[..., 2].astype(float) / 127.5 - 1.0, -1.0, 1.0)
        tilt = np.degrees(np.arccos(z))
        written[role] = {"file": out.name, "target_mean_tilt_deg": relief,
                         "mean_tilt_deg": round(float(np.mean(tilt)), 2),
                         "p95_tilt_deg": round(float(np.percentile(tilt, 95)), 2)}
    return written
