#!/usr/bin/env python3
"""Convert a .cube LUT to Unreal's 256x16 colour-grading LUT strip (PNG).

Visual round 5, lane L2 (the optional in-engine path). UE's ColorGradingLUT
texture is an unwrapped 16^3 table: a 256 x 16 image of 16 tiles side by
side, where within a tile x is red (0..15), y is green, and the tile index
along x is blue -- the layout of the engine's own neutral LUT
(Engine/Shaders/Private/PostProcessCombineLUTs.usf, UnwrappedTexture3DSample).
Each texel is the .cube sampled (tetrahedral, core/capture/display.py) at
that node, written as 8-bit sRGB. An identity cube converts to the neutral
strip within one code value (tests/test_film_luts.py).

On the Windows editor the strip is imported with
``lod_group = TEXTUREGROUP_ColorLookupTable`` (sRGB on, no mips) and set as
``ColorGradingLUT`` with ``ColorGradingIntensity``. The post-render path
(scripts/beauty_post.py, ffmpeg lut3d on the full 33^3 cube) is the one the
round prefers: full precision, and nothing to import.

    python scripts/cube_to_ue_lut.py assets/looks/film/kodak_portra_160.cube out.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

#: UE's unwrapped LUT: 16 tiles of 16 x 16.
TILE = 16
WIDTH = TILE * TILE
HEIGHT = TILE


def strip_nodes() -> np.ndarray:
    """The (16, 256, 3) sRGB-encoded input of every texel of the strip."""
    x = np.arange(WIDTH)
    r = (x % TILE) / (TILE - 1)
    b = (x // TILE) / (TILE - 1)
    g = np.arange(HEIGHT) / (TILE - 1)
    nodes = np.empty((HEIGHT, WIDTH, 3), dtype=np.float64)
    nodes[..., 0] = r[None, :]
    nodes[..., 1] = g[:, None]
    nodes[..., 2] = b[None, :]
    return nodes


def neutral_strip() -> np.ndarray:
    """The identity strip as 8-bit values (16, 256, 3)."""
    return np.clip(np.round(strip_nodes() * 255.0), 0, 255).astype(np.uint8)


def cube_to_strip(cube_path) -> np.ndarray:
    """The 8-bit (16, 256, 3) strip of the .cube at ``cube_path``."""
    from core.capture.display import read_cube, tetrahedral

    table, lo, hi = read_cube(cube_path)
    out = tetrahedral(strip_nodes(), table, lo, hi)
    return np.clip(np.round(out * 255.0), 0, 255).astype(np.uint8)


def write_strip(cube_path, png_path) -> Path:
    from PIL import Image

    strip = cube_to_strip(cube_path)
    Image.fromarray(strip).save(Path(png_path), format="PNG")
    return Path(png_path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cube", type=Path)
    parser.add_argument("png", type=Path)
    args = parser.parse_args(argv)
    out = write_strip(args.cube, args.png)
    print(f"{out}: {WIDTH}x{HEIGHT} UE colour-grading LUT from {args.cube.name}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.exit(main())
