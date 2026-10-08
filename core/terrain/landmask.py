"""Land or open ocean, anywhere, offline: the GLO-30 cell mask.

GLO-30 publishes a tile for every 1 x 1 degree cell containing land, so
the Copernicus bucket's tileList.txt is a one-degree land mask. It is
committed as assets/landmask/glo30_cells.txt (scripts/build_landmask.py
writes it; the sidecar records the source's sha256), so a place check
never touches the network.

What it supports: a cell WITHOUT a tile has no GLO-30 land, so it cannot
be baked, and its ground at sea level is the flat slab at 0 m;
:func:`open_ocean` asks that of the cell and its neighbours, so the
nearest land is at least ``margin`` cells (about 111 km each) away. A
cell WITH a tile has some land, not that the point itself is on land.

Not claimed: the public GLO-30 release lacks a few land cells (it
withholds tiles over Armenia and Azerbaijan), which read here as water;
inland seas and large lakes read as land cells wherever a shore shares
the cell.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import FrozenSet, Tuple

MASK_PATH = Path(__file__).resolve().parents[2] / "assets" / "landmask" / "glo30_cells.txt"
SIDECAR_PATH = MASK_PATH.with_suffix(".json")


@lru_cache(maxsize=1)
def land_cells() -> FrozenSet[Tuple[int, int]]:
    """Every (lat_floor, lon_floor) cell with a GLO-30 tile."""
    rows = MASK_PATH.read_text(encoding="ascii").split()
    if len(rows) != 180 or any(len(row) != 90 for row in rows):
        raise ValueError(f"{MASK_PATH} is not the 180 x 90 hex mask "
                         f"scripts/build_landmask.py writes")
    cells = set()
    for index, row in enumerate(rows):
        lat = 89 - index
        bits = "".join(f"{int(digit, 16):04b}" for digit in row)
        cells.update((lat, lon - 180) for lon, bit in enumerate(bits) if bit == "1")
    return frozenset(cells)


def _cell(lat: float, lon: float) -> Tuple[int, int]:
    return math.floor(float(lat)), (math.floor(float(lon)) + 180) % 360 - 180


def has_land(lat: float, lon: float) -> bool:
    """The point's one-degree cell has a GLO-30 tile."""
    return _cell(lat, lon) in land_cells()


def open_ocean(lat: float, lon: float, margin: int = 1) -> bool:
    """No GLO-30 tile in the point's cell nor within ``margin`` cells."""
    lat_cell, lon_cell = _cell(lat, lon)
    cells = land_cells()
    for la in range(lat_cell - margin, lat_cell + margin + 1):
        for lo in range(lon_cell - margin, lon_cell + margin + 1):
            if (la, (lo + 180) % 360 - 180) in cells:
                return False
    return True
