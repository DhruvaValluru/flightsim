"""Small drawing helpers for the annotation sheets -- PIL and numpy only.

Nothing here decides anything: these turn arrays and boxes into pixels
a person can look at. The verifier decides; the sheet shows what it
measured.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

RGB = Tuple[int, int, int]

#: One colour per object integer (1..); 0 (background) is near-black.
PALETTE: Sequence[RGB] = (
    (28, 28, 34),        # 0 background
    (66, 135, 245),      # 1 the primary: blue
    (245, 166, 35),      # 2: orange
    (96, 168, 96),       # 3: green (the terrain on a two-aircraft run)
    (200, 80, 200),      # 4
    (80, 200, 200),      # 5
    (200, 200, 80),      # 6
    (160, 110, 60),      # 7
)
RED: RGB = (255, 40, 40)
WHITE: RGB = (255, 255, 255)
YELLOW: RGB = (255, 230, 0)
CYAN: RGB = (0, 230, 255)
MAGENTA: RGB = (255, 0, 200)
GREEN: RGB = (60, 255, 60)
GREY: RGB = (120, 120, 120)


def font(size: int = 14):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                 # older Pillow: fixed-size default
        return ImageFont.load_default()


def colour_of(int_id: int) -> RGB:
    return PALETTE[int_id % len(PALETTE)] if int_id != 0 else PALETTE[0]


def colourise(ids) -> np.ndarray:
    """An (h, w) integer image -> (h, w, 3) uint8 through the palette."""
    ids = np.asarray(ids)
    out = np.zeros(ids.shape + (3,), dtype=np.uint8)
    for value in np.unique(ids):
        out[ids == value] = colour_of(int(value))
    return out


def dim(rgb: np.ndarray, factor: float = 0.45) -> np.ndarray:
    return (rgb.astype(float) * factor).astype(np.uint8)


def heatmap(depth, lo: Optional[float] = None, hi: Optional[float] = None) -> np.ndarray:
    """Finite depths on a five-stop gradient (near = dark blue, far =
    red); sky / non-finite black. lo/hi default to the 1st and 99th
    percentiles of the finite values."""
    depth = np.asarray(depth, dtype=float)
    finite = np.isfinite(depth)
    out = np.zeros(depth.shape + (3,), dtype=np.uint8)
    if not finite.any():
        return out
    values = depth[finite]
    lo = float(np.percentile(values, 1)) if lo is None else lo
    hi = float(np.percentile(values, 99)) if hi is None else hi
    if hi <= lo:
        hi = lo + 1.0
    t = np.clip((depth - lo) / (hi - lo), 0.0, 1.0)
    stops = np.array([(20, 30, 120), (0, 180, 220), (40, 200, 60),
                      (240, 220, 40), (230, 40, 30)], dtype=float)
    pos = t * (len(stops) - 1)
    idx = np.clip(np.floor(pos).astype(int), 0, len(stops) - 2)
    frac = (pos - idx)[..., None]
    rgb = stops[idx] * (1.0 - frac) + stops[idx + 1] * frac
    out[finite] = rgb[finite].astype(np.uint8)
    return out


def outline(mask) -> np.ndarray:
    """The boundary pixels of a boolean mask (4-neighbourhood)."""
    m = np.asarray(mask, dtype=bool)
    inner = m.copy()
    inner[1:, :] &= m[:-1, :]
    inner[:-1, :] &= m[1:, :]
    inner[:, 1:] &= m[:, :-1]
    inner[:, :-1] &= m[:, 1:]
    return m & ~inner


def paint(rgb: np.ndarray, where, colour: RGB) -> np.ndarray:
    rgb = rgb.copy()
    rgb[np.asarray(where, dtype=bool)] = colour
    return rgb


def to_image(rgb: np.ndarray) -> Image.Image:
    return Image.fromarray(np.ascontiguousarray(rgb.astype(np.uint8)), mode="RGB")


def box(draw: ImageDraw.ImageDraw, rect, colour: RGB, width: int = 2) -> None:
    if rect is None:
        return
    u0, v0, u1, v1 = (float(v) for v in rect)
    draw.rectangle([u0, v0, max(u1 - 1, u0), max(v1 - 1, v0)], outline=colour, width=width)


def cross(draw: ImageDraw.ImageDraw, point, colour: RGB, size: int = 8, width: int = 2) -> None:
    if point is None:
        return
    u, v = float(point[0]), float(point[1])
    draw.line([u - size, v, u + size, v], fill=colour, width=width)
    draw.line([u, v - size, u, v + size], fill=colour, width=width)


#: The twelve edges of a box whose corners are ordered
#: for x in (lo, hi), for y in (lo, hi), for z in (lo, hi).
BOX_EDGES: Sequence[Tuple[int, int]] = (
    (0, 1), (2, 3), (4, 5), (6, 7),
    (0, 2), (1, 3), (4, 6), (5, 7),
    (0, 4), (1, 5), (2, 6), (3, 7),
)


def wire(draw: ImageDraw.ImageDraw, corners_px, colour: RGB, width: int = 1) -> None:
    """A box's projected corners joined along its edges."""
    if corners_px is None or any(c is None for c in corners_px):
        return
    for a, b in BOX_EDGES:
        draw.line([corners_px[a][0], corners_px[a][1], corners_px[b][0], corners_px[b][1]],
                  fill=colour, width=width)


def label(draw: ImageDraw.ImageDraw, xy, text: str, colour: RGB = WHITE,
          size: int = 13, background: Optional[RGB] = (0, 0, 0)) -> None:
    f = font(size)
    x, y = float(xy[0]), float(xy[1])
    if background is not None:
        left, top, right, bottom = draw.textbbox((x, y), text, font=f)
        draw.rectangle([left - 2, top - 1, right + 2, bottom + 1], fill=background)
    draw.text((x, y), text, fill=colour, font=f)


def caption(image: Image.Image, lines: Iterable[str], size: int = 13,
            colour: RGB = WHITE, background: RGB = (16, 16, 20)) -> Image.Image:
    """The image with a text strip above it."""
    lines = list(lines)
    f = font(size)
    height = int(size * 1.5) * max(1, len(lines)) + 8
    out = Image.new("RGB", (image.width, image.height + height), background)
    draw = ImageDraw.Draw(out)
    for i, line in enumerate(lines):
        draw.text((6, 4 + i * int(size * 1.5)), line, fill=colour, font=f)
    out.paste(image, (0, height))
    return out


def side_by_side(images: Sequence[Image.Image], gap: int = 8,
                 background: RGB = (16, 16, 20)) -> Image.Image:
    if not images:
        return Image.new("RGB", (64, 64), background)
    width = sum(i.width for i in images) + gap * (len(images) - 1)
    height = max(i.height for i in images)
    out = Image.new("RGB", (width, height), background)
    x = 0
    for image in images:
        out.paste(image, (x, 0))
        x += image.width + gap
    return out


def stack(images: Sequence[Image.Image], gap: int = 8,
          background: RGB = (16, 16, 20)) -> Image.Image:
    if not images:
        return Image.new("RGB", (64, 64), background)
    width = max(i.width for i in images)
    height = sum(i.height for i in images) + gap * (len(images) - 1)
    out = Image.new("RGB", (width, height), background)
    y = 0
    for image in images:
        out.paste(image, (0, y))
        y += image.height + gap
    return out


def shrink(image: Image.Image, max_width: int) -> Image.Image:
    if image.width <= max_width:
        return image
    scale = max_width / image.width
    return image.resize((max_width, max(1, int(image.height * scale))), Image.NEAREST)


def legend(entries: Dict[str, RGB], size: int = 13) -> Image.Image:
    """A one-line legend strip: a swatch and a name per entry."""
    f = font(size)
    width = 8 + sum(size + 6 + int(size * 0.62 * len(name)) + 18 for name in entries)
    out = Image.new("RGB", (max(width, 64), int(size * 1.8)), (16, 16, 20))
    draw = ImageDraw.Draw(out)
    x = 6
    for name, colour in entries.items():
        draw.rectangle([x, 4, x + size, 4 + size], fill=colour)
        draw.text((x + size + 4, 2), name, fill=WHITE, font=f)
        x += size + 6 + int(size * 0.62 * len(name)) + 18
    return out
