"""Build assets/landmask/glo30_cells.txt from the Copernicus bucket's tile list.

GLO-30 publishes one tile per 1 x 1 degree cell that contains land, so the
bucket's own tileList.txt IS a land mask at one-degree resolution. This
writes it as 180 rows (latitude 89 down to -90), each 90 hex digits (the
360 longitude cells -180..179, four per digit, most significant bit
first), plus a sidecar recording the source, its sha256 and the count.

    python scripts/build_landmask.py            # fetch and write
    python scripts/build_landmask.py --check    # fetch and compare
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.terrain.glo30 import BUCKET  # noqa: E402
from core.terrain.landmask import MASK_PATH, SIDECAR_PATH  # noqa: E402

SOURCE = f"{BUCKET}/tileList.txt"
STEM = re.compile(r"Copernicus_DSM_COG_10_([NS])(\d{2})_00_([EW])(\d{3})_00_DEM")


def cells_from(listing: str):
    cells = set()
    for line in listing.split():
        match = STEM.fullmatch(line.strip())
        if match:
            ns, lat, ew, lon = match.groups()
            cells.add((int(lat) * (1 if ns == "N" else -1),
                       int(lon) * (1 if ew == "E" else -1)))
    return cells


def render(cells) -> str:
    rows = []
    for lat in range(89, -91, -1):
        bits = "".join("1" if (lat, lon) in cells else "0" for lon in range(-180, 180))
        rows.append("".join(f"{int(bits[i:i + 4], 2):x}" for i in range(0, 360, 4)))
    return "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    with urllib.request.urlopen(SOURCE, timeout=120) as response:
        raw = response.read()
    cells = cells_from(raw.decode("utf-8"))
    text = render(cells)
    sidecar = {"source": SOURCE, "source_sha256": hashlib.sha256(raw).hexdigest(),
               "land_cells": len(cells),
               "format": "180 rows, lat 89..-90; 90 hex digits per row, lon -180..179, "
                         "MSB first; 1 = a GLO-30 tile exists for the cell",
               "mask_sha256": hashlib.sha256(text.encode("ascii")).hexdigest()}
    if args.check:
        same = MASK_PATH.read_text(encoding="ascii") == text
        print("unchanged" if same else "DIFFERS from the committed mask")
        return 0 if same else 1
    MASK_PATH.parent.mkdir(parents=True, exist_ok=True)
    MASK_PATH.write_text(text, encoding="ascii", newline="\n")
    SIDECAR_PATH.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    print(f"{len(cells)} land cells -> {MASK_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
